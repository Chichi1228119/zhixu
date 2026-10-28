"""BM25 and TF-IDF lexical retrieval, fused by reciprocal rank."""

import re
import unicodedata

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

_STOP_WORDS = {'a', 'an', 'the', 'is', 'are', 'of', 'to', 'for', 'in', 'and', 'what', 'how',
               '公司', '员工', '请问', '多少', '什么', '如何', '是否', '有没有', '可以', '需要', '规定'}


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize('NFKC', text).lower()
    tokens = []
    for word in re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+', text):
        if re.fullmatch(r'[a-z0-9]+', word):
            if word not in _STOP_WORDS:
                tokens.append(word)
        else:
            for size in (2, 3):
                tokens.extend(word[i:i + size] for i in range(len(word) - size + 1)
                              if word[i:i + size] not in _STOP_WORDS)
    return tokens


class Retriever:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.tokens = [tokenize(c['text']) for c in chunks]
        self.bm25 = None
        self.vectorizer = None
        self.matrix = None
        if chunks and any(self.tokens):
            self.bm25 = BM25Okapi(self.tokens)
            self.vectorizer = TfidfVectorizer(analyzer=tokenize, norm='l2')
            self.matrix = self.vectorizer.fit_transform([c['text'] for c in chunks])

    def search(self, question: str, top_k: int = 5, document_ids: list[str] | None = None,
               strategy: str = 'hybrid') -> list[dict]:
        if strategy not in {'hybrid', 'bm25', 'tfidf'}:
            raise ValueError('strategy 只能是 hybrid、bm25 或 tfidf。')
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
            raise ValueError('top_k 须在 1 到 20 之间。')
        query_tokens = tokenize(question)
        if not query_tokens or self.bm25 is None:
            return []
        query_set = set(query_tokens)
        allowed = set(document_ids) if document_ids else None
        bm25 = self.bm25.get_scores(query_tokens)
        similarities = (self.matrix @ self.vectorizer.transform([question]).T).toarray().ravel()
        candidates = []
        for i, chunk in enumerate(self.chunks):
            if allowed is not None and chunk['document_id'] not in allowed:
                continue
            overlap = query_set.intersection(self.tokens[i])
            coverage = len(overlap) / len(query_set)
            # Require multiple lexical anchors, rather than a generic shared word.
            if not overlap or similarities[i] < 0.06:
                continue
            if len(query_set) >= 4 and (len(overlap) < 2 or coverage < 0.10):
                continue
            candidates.append(i)
        if not candidates:
            return []
        lexical_order = sorted(candidates, key=lambda i: (-float(bm25[i]), i))
        vector_order = sorted(candidates, key=lambda i: (-float(similarities[i]), i))
        if strategy == 'bm25':
            order = lexical_order
            scores = {i: float(bm25[i]) for i in candidates}
        elif strategy == 'tfidf':
            order = vector_order
            scores = {i: float(similarities[i]) for i in candidates}
        else:
            scores = {i: 0.0 for i in candidates}
            for ranking in (lexical_order, vector_order):
                for rank, i in enumerate(ranking, 1):
                    scores[i] += 1.0 / (60 + rank)
            order = sorted(candidates, key=lambda i: (-scores[i], i))
        return [dict(self.chunks[i], score=round(scores[i], 8)) for i in order[:top_k]]
