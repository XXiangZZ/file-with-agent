"""LangChain retriever: lexical baseline + local latent semantic analysis hybrid.

LSA is fitted on the current local corpus, not a pretrained language model.
Optional configured embeddings replace LSA when explicitly permitted.
"""
import math
import re
from collections import Counter
from typing import Any
from langchain_core.retrievers import BaseRetriever

ALIASES = {'标题': '题名', '发文单位': '责任者', '落款单位': '责任者',
           '落款时间': '日期', '形成时间': '日期', '日其': '日期'}
STOP = set('的了是在应如何什么怎么填写著录请问按与及为要')


def tokens(text, expanded=False):
    if expanded:
        for alias, canonical in ALIASES.items():
            text = text.replace(alias, canonical)
    words = re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]', text.lower())
    words = [w for w in words if w not in STOP]
    return Counter(words + ([a+b for a, b in zip(words, words[1:])] if expanded else []))


def cosine(a, b):
    denom = math.sqrt(sum(v*v for v in a.values()) * sum(v*v for v in b.values()))
    return sum(v*b.get(k, 0) for k, v in a.items()) / denom if denom else 0


def latent_scores(query, docs):
    """Small-corpus TF-IDF/SVD semantic baseline; no downloads or external calls."""
    import numpy as np
    counters = [tokens(d.page_content, True) for d in docs]
    vocabulary = sorted({word for counts in counters for word in counts})
    if not vocabulary:
        return [0.] * len(docs)
    idf = np.array([math.log((1 + len(docs)) / (1 + sum(w in c for c in counters))) + 1 for w in vocabulary])
    matrix = np.array([[c.get(w, 0) for w in vocabulary] for c in counters], dtype=float) * idf
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    _, _, vt = np.linalg.svd(matrix, full_matrices=False)
    # Limit latent dimensions for larger corpora; deterministic for this fixed input.
    basis = vt[:min(32, max(1, len(docs) - 1))].T
    counts = tokens(query, True)
    q = np.array([counts.get(w, 0) for w in vocabulary]) * idf
    q = q @ basis
    vectors = matrix @ basis
    scores = vectors @ q / np.maximum(np.linalg.norm(vectors, axis=1) * np.linalg.norm(q), 1e-12)
    return scores.tolist()


class ArchiveRetriever(BaseRetriever):
    index: Any
    scope: str = '通用'
    mode: str = 'hybrid'
    k: int = 4
    embeddings: Any = None
    kinds: list[str] | None = None

    def _get_relevant_documents(self, query, *, run_manager):
        docs = self.index.documents(self.scope, self.kinds)
        if not docs or not query.strip():
            return []
        q = tokens(query, self.mode != 'keyword')
        vectors = None
        semantic = latent_scores(query, docs) if self.mode != 'keyword' else [0.] * len(docs)
        if self.embeddings is not None and self.mode != 'keyword':
            vectors = self.embeddings.embed_documents([d.page_content for d in docs])
            query_vector = self.embeddings.embed_query(query)
            if len(query_vector) != len(vectors[0]):
                raise ValueError('文档和问题嵌入维度不一致')
        ranked = []
        for i, doc in enumerate(docs):
            score = cosine(q, tokens(doc.page_content, self.mode != 'keyword'))
            if vectors is not None:
                score = (score + cosine(dict(enumerate(query_vector)), dict(enumerate(vectors[i])))) / 2
            elif self.mode != 'keyword':
                score = .6 * score + .4 * max(0, semantic[i])
            if score > 0:
                doc.metadata['retrieval_score'] = score
                ranked.append((score, doc))
        return [d for _, d in sorted(ranked, key=lambda row: (-row[0], row[1].metadata['id']))[:self.k]]
