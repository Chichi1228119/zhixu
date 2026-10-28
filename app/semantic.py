"""Optional, local-only Chinese sentence-vector retrieval."""

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_NAME = 'BAAI/bge-small-zh-v1.5'
QUERY_INSTRUCTION = '为这个句子生成表示以用于检索相关文章：'
# This fixed cosine cutoff is uncalibrated and is not a probability.
MIN_SIMILARITY = 0.65
_REQUIRED_FILES = ('model_optimized.onnx', 'config.json', 'tokenizer.json',
                   'tokenizer_config.json', 'special_tokens_map.json')


class SemanticUnavailable(ValueError):
    """The optional local semantic model is not ready."""


def _ready_snapshot(cache_dir: Path) -> Path | None:
    root = Path(cache_dir).resolve()
    try:
        manifest = json.loads((root / 'semantic-ready.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or manifest.get('verified') is not True or manifest.get('model') != MODEL_NAME:
            return None
        repository = root / 'models--Qdrant--bge-small-zh-v1.5'
        revision = (repository / 'refs' / 'main').read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'[a-fA-F0-9]{40,64}', revision):
            return None
        snapshot = repository / 'snapshots' / revision
        for name in _REQUIRED_FILES:
            file = snapshot / name
            if not file.is_file() or not file.resolve().is_relative_to(root) or file.stat().st_size == 0:
                return None
        return snapshot
    except (OSError, ValueError, TypeError):
        return None


def semantic_available(cache_dir: Path) -> bool:
    """Check the verified marker and usable cache files without loading a model."""
    return _ready_snapshot(cache_dir) is not None


@lru_cache(maxsize=2)
def _load_embedder(cache_key: str):
    root = Path(cache_key)
    snapshot = _ready_snapshot(root)
    if snapshot is None:
        raise SemanticUnavailable('本地语义模型未就绪，请先显式运行模型下载与验证脚本。')
    os.environ['HF_HOME'] = str(root / 'huggingface')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    try:
        from fastembed import TextEmbedding
        return TextEmbedding(model_name=MODEL_NAME, cache_dir=str(root),
                             specific_model_path=str(snapshot), local_files_only=True,
                             threads=2, providers=['CPUExecutionProvider'])
    except Exception as exc:
        raise SemanticUnavailable('本地语义模型加载失败，请重新验证本地模型文件；未尝试联网下载。') from exc


def _normalized(vectors: np.ndarray) -> np.ndarray:
    if vectors.ndim != 2 or not np.isfinite(vectors).all():
        raise SemanticUnavailable('本地语义模型返回了无效向量。')
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


class SemanticRetriever:
    def __init__(self, chunks: list[dict], cache_dir: Path, embedder=None):
        self.chunks = [dict(chunk) for chunk in chunks]
        if embedder is None:
            if not semantic_available(cache_dir):
                raise SemanticUnavailable('本地语义模型未就绪，请先显式运行模型下载与验证脚本。')
            embedder = _load_embedder(str(Path(cache_dir).resolve()))
        self.embedder = embedder
        self.matrix = np.empty((0, 0), dtype=np.float32)
        if self.chunks:
            try:
                vectors = np.asarray(list(embedder.embed([chunk['text'] for chunk in self.chunks], batch_size=32)), dtype=np.float32)
                if vectors.ndim != 2 or vectors.shape[0] != len(self.chunks):
                    raise SemanticUnavailable('本地语义模型返回的片段向量数量或形状不正确。')
                self.matrix = _normalized(vectors)
            except Exception as exc:
                raise SemanticUnavailable('本地语义模型无法编码资料，请检查模型文件。') from exc

    def search(self, question: str, top_k: int = 5,
               document_ids: list[str] | None = None) -> list[dict]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
            raise ValueError('top_k 须在 1 到 20 之间。')
        if not question.strip() or not self.chunks:
            return []
        try:
            vectors = np.asarray(list(self.embedder.query_embed(QUERY_INSTRUCTION + question.strip())), dtype=np.float32)
            if vectors.shape != (1, self.matrix.shape[1]):
                raise SemanticUnavailable('本地语义模型返回的问题向量形状不正确。')
            query = _normalized(vectors)[0]
        except Exception as exc:
            raise SemanticUnavailable('本地语义模型无法编码问题，请检查模型文件。') from exc
        scores = np.clip(self.matrix @ query, -1, 1)
        allowed = set(document_ids) if document_ids else None
        candidates = [i for i, chunk in enumerate(self.chunks)
                      if scores[i] >= MIN_SIMILARITY and (allowed is None or chunk['document_id'] in allowed)]
        ranking = sorted(candidates, key=lambda i: (-float(scores[i]), i))
        return [dict(self.chunks[i], score=round(float(scores[i]), 8)) for i in ranking[:top_k]]
