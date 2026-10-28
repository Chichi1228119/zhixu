import copy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.semantic import SemanticRetriever, SemanticUnavailable, semantic_available


MODEL = 'BAAI/bge-small-zh-v1.5'
INSTRUCTION = '为这个句子生成表示以用于检索相关文章：'


def _chunks():
    return [
        {'id': 'c1', 'document_id': 'd1', 'filename': 'remote.txt', 'location': '第 1 段',
         'text': '员工每周可以在家处理两天工作。'},
        {'id': 'c2', 'document_id': 'd2', 'filename': 'expenses.txt', 'location': '第 2 段',
         'text': '差旅票据应在返程后提交。'},
        {'id': 'c3', 'document_id': 'd3', 'filename': 'payroll.txt', 'location': '第 3 段',
         'text': '工资每月十五日发放。'},
    ]


class FakeEmbedder:
    def __init__(self):
        self.document_vectors = {
            _chunks()[0]['text']: [3, 4, 0],
            _chunks()[1]['text']: [4, 3, 0],
            _chunks()[2]['text']: [0, 0, 5],
        }
        self.query_vectors = {
            '远程办公额度有几天？': [6, 8, 0],
            '工资发放日': [0, 0, 2],
            '完全无关的问题': [0, 0, -5],
            '零向量问题': [0, 0, 0],
        }
        self.queries = []
        self.documents = []

    def embed(self, documents, **kwargs):
        documents = list(documents)
        self.documents.extend(documents)
        return iter(np.array(self.document_vectors[text], dtype=np.float32) for text in documents)

    def query_embed(self, query, **kwargs):
        self.queries.append(query)
        assert query.startswith(INSTRUCTION)
        return iter([np.array(self.query_vectors[query.removeprefix(INSTRUCTION)], dtype=np.float32)])


@pytest.fixture
def index(tmp_path):
    return SemanticRetriever(_chunks(), tmp_path, embedder=FakeEmbedder())


def test_semantic_vectors_can_match_different_wording(index):
    sources = index.search('远程办公额度有几天？')
    assert sources[0]['id'] == 'c1'
    assert sources[0]['text'] == _chunks()[0]['text']
    assert sources[0]['score'] == pytest.approx(1.0)


def test_results_are_normalized_sorted_and_capped(index):
    sources = index.search('远程办公额度有几天？', top_k=2)
    assert [source['id'] for source in sources] == ['c1', 'c2']
    assert [source['score'] for source in sources] == pytest.approx([1.0, 0.96])
    assert len(index.search('远程办公额度有几天？', top_k=1)) == 1
    assert all(-1 <= source['score'] <= 1 for source in sources)


def test_document_filter_keeps_source_metadata(index):
    sources = index.search('远程办公额度有几天？', document_ids=['d2'])
    assert len(sources) == 1
    assert sources[0] == dict(_chunks()[1], score=pytest.approx(0.96))
    assert index.search('远程办公额度有几天？', document_ids=['missing']) == []
    assert index.search('远程办公额度有几天？', document_ids=[]) == index.search('远程办公额度有几天？')


@pytest.mark.parametrize('question', ['', '   ', '\n\t'])
def test_empty_question_never_embeds_query(tmp_path, question):
    fake = FakeEmbedder()
    index = SemanticRetriever(_chunks(), tmp_path, embedder=fake)
    assert index.search(question) == []
    assert fake.queries == []


@pytest.mark.parametrize('question', ['完全无关的问题', '零向量问题'])
def test_below_threshold_or_zero_vector_returns_no_source(index, question):
    assert index.search(question) == []


@pytest.mark.parametrize('top_k', [0, -1, 21, 1.5, True])
def test_invalid_top_k_is_rejected(index, top_k):
    with pytest.raises(ValueError, match='top_k'):
        index.search('远程办公额度有几天？', top_k=top_k)


def test_sources_do_not_modify_input_chunks(tmp_path):
    chunks = _chunks()
    original = copy.deepcopy(chunks)
    index = SemanticRetriever(chunks, tmp_path, embedder=FakeEmbedder())
    source = index.search('远程办公额度有几天？')[0]
    source['text'] = 'changed returned copy'
    assert chunks == original
    assert index.search('远程办公额度有几天？')[0]['text'] == original[0]['text']


def test_empty_index_never_calls_embedder(tmp_path):
    fake = FakeEmbedder()
    index = SemanticRetriever([], tmp_path, embedder=fake)
    assert index.search('工资发放日') == []
    assert fake.documents == fake.queries == []


def test_zero_document_vector_is_excluded(tmp_path):
    fake = FakeEmbedder()
    fake.document_vectors[_chunks()[0]['text']] = [0, 0, 0]
    index = SemanticRetriever(_chunks(), tmp_path, embedder=fake)
    assert [source['id'] for source in index.search('远程办公额度有几天？')] == ['c2']


def test_equal_scores_use_original_order(tmp_path):
    fake = FakeEmbedder()
    fake.document_vectors[_chunks()[1]['text']] = [3, 4, 0]
    index = SemanticRetriever(_chunks(), tmp_path, embedder=fake)
    assert [source['id'] for source in index.search('远程办公额度有几天？')] == ['c1', 'c2']


def _ready_cache(cache_dir):
    repository = cache_dir / 'models--Qdrant--bge-small-zh-v1.5'
    (repository / 'refs').mkdir(parents=True)
    (repository / 'refs' / 'main').write_text('a' * 40, encoding='utf-8')
    snapshot = repository / 'snapshots' / ('a' * 40)
    snapshot.mkdir(parents=True)
    for name in ('model_optimized.onnx', 'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'):
        (snapshot / name).write_bytes(b'fake-local-file')
    (cache_dir / 'semantic-ready.json').write_text(json.dumps({'model': MODEL, 'verified': True}), encoding='utf-8')
    return snapshot


def test_available_requires_manifest_and_actual_snapshot_files(tmp_path):
    assert semantic_available(tmp_path) is False
    snapshot = _ready_cache(tmp_path)
    assert semantic_available(tmp_path) is True
    (snapshot / 'model_optimized.onnx').unlink()
    assert semantic_available(tmp_path) is False


@pytest.mark.parametrize('manifest', [{'model': MODEL, 'verified': False}, {'model': MODEL, 'verified': 'true'}, {'model': 'wrong/model', 'verified': True}, [], None])
def test_invalid_readiness_manifest_is_unavailable(tmp_path, manifest):
    _ready_cache(tmp_path)
    (tmp_path / 'semantic-ready.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert semantic_available(tmp_path) is False


@pytest.mark.parametrize('missing_file', ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'])
def test_missing_tokenizer_or_model_configuration_is_unavailable(tmp_path, missing_file):
    snapshot = _ready_cache(tmp_path)
    (snapshot / missing_file).unlink()
    assert semantic_available(tmp_path) is False


def test_empty_weights_and_malformed_manifest_are_unavailable(tmp_path):
    snapshot = _ready_cache(tmp_path)
    (snapshot / 'model_optimized.onnx').write_bytes(b'')
    assert semantic_available(tmp_path) is False
    (tmp_path / 'semantic-ready.json').write_text('{invalid', encoding='utf-8')
    assert semantic_available(tmp_path) is False


def test_missing_model_is_clear_error_without_loading_or_downloading(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'fastembed', SimpleNamespace(TextEmbedding=lambda **kwargs: calls.append(kwargs)))
    with pytest.raises(SemanticUnavailable, match='模型.*未就绪'):
        SemanticRetriever(_chunks(), tmp_path)
    assert calls == []


def test_runtime_is_local_cpu_only_and_model_is_cached_per_directory(tmp_path, monkeypatch):
    snapshot = _ready_cache(tmp_path)
    calls = []

    def load(**kwargs):
        calls.append(kwargs)
        assert os.environ['HF_HOME'] == str(tmp_path / 'huggingface')
        assert os.environ['HF_HUB_DISABLE_TELEMETRY'] == '1'
        assert os.environ.get('HF_HUB_OFFLINE') != '1'
        return FakeEmbedder()

    monkeypatch.setitem(sys.modules, 'fastembed', SimpleNamespace(TextEmbedding=load))
    monkeypatch.setenv('HF_HOME', 'previous-cache')
    monkeypatch.setenv('HF_HUB_DISABLE_TELEMETRY', '0')
    monkeypatch.delenv('HF_HUB_OFFLINE', raising=False)
    SemanticRetriever(_chunks(), tmp_path)
    SemanticRetriever(_chunks(), tmp_path / '.')
    assert len(calls) == 1
    assert calls[0]['model_name'] == MODEL
    assert calls[0]['local_files_only'] is True
    assert calls[0]['threads'] == 2
    assert calls[0]['providers'] == ['CPUExecutionProvider']
    assert calls[0]['specific_model_path'] == str(snapshot)


def test_distinct_cache_directories_do_not_share_loaded_models(tmp_path, monkeypatch):
    calls = []
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    _ready_cache(first)
    _ready_cache(second)

    def load(**kwargs):
        calls.append(kwargs['cache_dir'])
        return FakeEmbedder()

    monkeypatch.setitem(sys.modules, 'fastembed', SimpleNamespace(TextEmbedding=load))
    monkeypatch.setenv('HF_HOME', 'previous-cache')
    monkeypatch.setenv('HF_HUB_DISABLE_TELEMETRY', '0')
    SemanticRetriever(_chunks(), first)
    SemanticRetriever(_chunks(), second)
    assert calls == [str(first), str(second)]


def test_backend_load_failure_becomes_clear_unavailable_error(tmp_path, monkeypatch):
    _ready_cache(tmp_path)

    def fail(**kwargs):
        assert kwargs['local_files_only'] is True
        raise OSError('unreadable local weights')

    monkeypatch.setitem(sys.modules, 'fastembed', SimpleNamespace(TextEmbedding=fail))
    monkeypatch.setenv('HF_HOME', 'previous-cache')
    monkeypatch.setenv('HF_HUB_DISABLE_TELEMETRY', '0')
    with pytest.raises(SemanticUnavailable, match='本地语义模型.*加载失败'):
        SemanticRetriever(_chunks(), tmp_path)


@pytest.mark.skipif(not semantic_available(Path(__file__).resolve().parents[1] / 'models'),
                    reason='Optional verified local model is not installed; this test never downloads it.')
def test_optional_real_local_model_matches_self_written_chinese_paraphrase():
    chunks = [
        {'id': 'local-work', 'document_id': 'local-1', 'filename': 'self-written.txt',
         'location': '第 1 段', 'text': '工作人员如需在家上班，须先得到直属主管同意。'},
        {'id': 'local-plant', 'document_id': 'local-2', 'filename': 'self-written.txt',
         'location': '第 2 段', 'text': '盆栽应放置在散射光照处，并根据土壤干燥情况适量浇水。'},
    ]
    index = SemanticRetriever(chunks, Path(__file__).resolve().parents[1] / 'models')
    sources = index.search('居家工作需要得到领导的批准吗？')
    assert [source['id'] for source in sources] == ['local-work']
    assert 0.65 <= sources[0]['score'] <= 1
