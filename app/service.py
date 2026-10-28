"""Document lifecycle and auditable, verbatim local answers."""

import hashlib
import re
import threading
import time
from pathlib import Path

from .ingestion import parse_document
from .retrieval import Retriever, tokenize
from .store import Store
from .paths import RuntimePaths


def _conflicting_numeric_rules(sources: list[dict]) -> bool:
    rules = {}
    number_pattern = r'(?<![A-Za-z0-9_])\d+(?:\.\d+)?'
    for source in sources:
        for sentence in re.split(r'[。！？\n]', source['text']):
            sentence = re.sub(r'\s+', '', sentence)
            numbers = tuple(re.findall(number_pattern, sentence))
            if not numbers:
                continue
            template = re.sub(number_pattern, '#', sentence)
            if len(template) < 8:
                continue
            previous = rules.setdefault(template, set())
            previous.add(numbers)
            if len(previous) > 1:
                return True
    return False


def _explicitly_missing(question: str, sources: list[dict]) -> bool:
    query = set(tokenize(question))
    missing_overlap = 0
    provided_overlap = 0
    for source in sources:
        for clause in re.split(r'[。！？；;\n，,]|但是|然而|不过|但|且', source['text']):
            if not clause.strip() or clause.lstrip().startswith('#'):
                continue
            overlap = len(query.intersection(tokenize(clause)))
            if re.search(r'未规定|未提供|未列出|没有列出|未公布|没有提供|暂未明确|未明确|未说明', clause):
                missing_overlap = max(missing_overlap, overlap)
            else:
                provided_overlap = max(provided_overlap, overlap)
    # A missing statement must match the question at least as strongly as any
    # provided fact; an unrelated missing attribute does not trigger refusal.
    return missing_overlap >= 2 and missing_overlap >= provided_overlap


class KnowledgeService:
    def __init__(self, db_path: Path, model_cache: Path | None = None):
        self.db_path = Path(db_path)
        self.store = Store(self.db_path)
        self._lock = threading.RLock()
        self._retriever = None
        self.model_cache = Path(model_cache) if model_cache else RuntimePaths.discover().model_dir
        self._semantic = None

    def import_document(self, filename: str, content: bytes) -> dict:
        # Validate before deduplication so an unsupported upload cannot bypass validation.
        parsed = parse_document(filename, content)
        digest = hashlib.sha256(content).hexdigest()
        with self._lock:
            existing = self.store.by_hash(digest)
            if existing:
                return dict(existing, existing=True)
            document = self.store.add(parsed, len(content), digest)
            self._retriever = None
            self._semantic = None
            return dict(document, existing=False)

    def documents(self) -> list[dict]:
        with self._lock:
            return self.store.documents()

    def document(self, doc_id: str) -> dict:
        with self._lock:
            return self.store.document(doc_id)

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            deleted = self.store.delete(doc_id)
            if deleted:
                self._retriever = None
                self._semantic = None
            return deleted

    def search(self, question: str, top_k: int = 5, document_ids: list[str] | None = None,
               strategy: str = 'hybrid') -> list[dict]:
        with self._lock:
            if strategy == 'semantic':
                if self._semantic is None:
                    from .semantic import SemanticRetriever
                    self._semantic = SemanticRetriever(self.store.chunks(), self.model_cache)
                return self._semantic.search(question, top_k, document_ids)
            if self._retriever is None:
                self._retriever = Retriever(self.store.chunks())
            return self._retriever.search(question, top_k, document_ids, strategy)

    def ask(self, question: str, top_k: int = 5, document_ids: list[str] | None = None,
            strategy: str = 'hybrid') -> dict:
        started = time.perf_counter()
        with self._lock:
            sources = self.search(question, top_k, document_ids, strategy)
            retrieval_ms = (time.perf_counter() - started) * 1000
            status = 'insufficient'
            warning = '本地原文摘录模式，未调用大模型；检索相关性与规则冲突仍需人工核对。'
            if not sources:
                answer = '当前资料中没有找到足够相关的依据，请补充资料或明确问题。'
            else:
                if _explicitly_missing(question, sources):
                    status = 'insufficient'
                    prefix = '检索到与问题相关的资料缺失说明，当前依据不足：\n\n'
                elif _conflicting_numeric_rules(sources):
                    status = 'conflict'
                    prefix = '发现相同表述的数字规则不一致，请核对版本与适用条件。\n\n'
                else:
                    status = 'answered'
                    prefix = '以下为检索到的原文摘录：\n\n'
                answer = prefix + '\n\n'.join(f'[{i}] {source["text"]}' for i, source in enumerate(sources, 1))
            return {'question': question, 'answer': answer, 'status': status, 'mode': 'extractive',
                    'sources': sources,
                    'metrics': {'retrieval_ms': round(retrieval_ms, 3),
                                'total_ms': round((time.perf_counter() - started) * 1000, 3),
                                'generation_ms': 0},
                    'trace': [{'label': '检索策略', 'detail': {'hybrid': 'BM25 + TF-IDF 稀疏向量，RRF 排名融合', 'bm25': 'BM25 词项检索', 'tfidf': 'TF-IDF 稀疏向量余弦相似度', 'semantic': '本机 BGE-small-zh-v1.5 · 512 维语义向量 · 固定 0.65 门限，非正确概率'}[strategy]},
                              {'label': '证据', 'detail': f'保留 {len(sources)} 个片段；编号对应下方来源。'},
                              {'label': '回答方式', 'detail': '逐字摘录原文；没有模型生成步骤。'}],
                    'warning': warning, 'usage': None}
