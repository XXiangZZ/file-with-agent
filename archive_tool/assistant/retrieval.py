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
REWRITE_ALIASES = {'咋办': '如何处理', '怎么弄': '如何处理', '查一下': '检索',
                   '找一下': '检索', '导出来': '导出', '保存下来': '保存'}
FIELD_TERMS = ('题名', '标题', '日期', '责任者', '发文单位', '密级', '件号', '保管期限')
MANUAL_TERMS = ('怎么', '如何操作', '步骤', '导入', '导出', '保存', '草稿', '检索', 'OCR', '点击')


def tokens(text, expanded=False):
    if expanded:
        for alias, canonical in ALIASES.items():
            text = text.replace(alias, canonical)
    words = re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]', text.lower())
    words = [w for w in words if w not in STOP]
    return Counter(words + ([a+b for a, b in zip(words, words[1:])] if expanded else []))


def rewrite_query(query):
    rewritten = query.strip()
    for alias, canonical in REWRITE_ALIASES.items():
        rewritten = rewritten.replace(alias, canonical)
    for alias, canonical in ALIASES.items():
        rewritten = rewritten.replace(alias, canonical)
    additions = []
    for concept, terms in {
        '题名': ('文件标题', '标题'), '责任者': ('署名单位', '发文单位'),
        '日期': ('形成日期', '落款时间'), '导出': ('批次导出', 'Excel 导出'),
        '导入': ('Excel 导入', '批量导入'), '草稿': ('保存草稿', '恢复草稿'),
    }.items():
        if concept in rewritten:
            additions.extend(terms)
    return ' '.join([rewritten, *additions]) if additions else rewritten


def route_intent(query):
    normalized = rewrite_query(query).lower()
    if any(term in normalized for term in FIELD_TERMS):
        return 'field'
    if any(term.lower() in normalized for term in MANUAL_TERMS):
        return 'manual'
    return 'policy'


def local_rerank(query, rewritten, doc, retrieval_score, intent):
    query_terms = set(tokens(query, True))
    rewritten_terms = set(tokens(rewritten, True))
    document_terms = set(tokens(doc.page_content, True))
    coverage = len(query_terms & document_terms) / max(1, len(query_terms))
    expanded_coverage = len(rewritten_terms & document_terms) / max(1, len(rewritten_terms))
    phrase = 1.0 if query.strip() and query.strip() in doc.page_content else 0.0
    heading = next((line for line in doc.page_content.splitlines() if line.strip()), '')
    heading_match = bool(set(tokens(heading, True)) & query_terms)
    kind_match = ((intent == 'manual' and doc.metadata.get('kind') == '手册') or
                  (intent in {'field', 'policy'} and doc.metadata.get('kind') == '规范'))
    return (.50 * retrieval_score + .22 * coverage + .12 * expanded_coverage
            + .08 * phrase + .05 * heading_match + .03 * kind_match)


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
        intent = route_intent(query)
        effective_kinds = self.kinds
        if effective_kinds is None and intent == 'manual':
            effective_kinds = ['手册']
        elif effective_kinds is None and intent == 'field':
            effective_kinds = ['规范']
        rewritten = rewrite_query(query)
        use_vectors = self.embeddings is not None and self.mode != 'keyword'
        persisted = self.index.vector_rows(self.scope, effective_kinds,
            expected_model=getattr(self.embeddings, 'model_name', None)) if use_vectors else []
        docs = [doc for doc, _ in persisted] if use_vectors else self.index.documents(self.scope, effective_kinds)
        if not docs or not query.strip():
            return []
        q = tokens(rewritten, self.mode != 'keyword')
        vectors = None
        semantic = latent_scores(rewritten, docs) if self.mode != 'keyword' and not use_vectors else [0.] * len(docs)
        if use_vectors:
            stored = {doc.metadata.get('id'): vector for doc, vector in persisted if vector is not None}
            if len(stored) == len(docs):
                vectors = [stored[d.metadata['id']] for d in docs]
            else:
                # A missing vector is an index lifecycle error; do not silently claim semantic retrieval.
                raise ValueError('知识库缺少持久化向量，请先使用当前嵌入模型重建索引')
            query_vector = self.embeddings.embed_query(rewritten)
            if len(query_vector) != len(vectors[0]):
                raise ValueError('文档和问题嵌入维度不一致')
        candidates = []
        for i, doc in enumerate(docs):
            score = cosine(q, tokens(doc.page_content, self.mode != 'keyword'))
            if vectors is not None:
                score = (score + cosine(dict(enumerate(query_vector)), dict(enumerate(vectors[i])))) / 2
            elif self.mode != 'keyword':
                score = .6 * score + .4 * max(0, semantic[i])
            if score > 0:
                doc.metadata['retrieval_score'] = score
                candidates.append((score, doc))
        candidate_limit = min(len(candidates), max(self.k, self.k * 3))
        candidates = sorted(candidates, key=lambda row: (-row[0], row[1].metadata['id']))[:candidate_limit]
        reranked = []
        for score, doc in candidates:
            final_score = local_rerank(query, rewritten, doc, score, intent)
            doc.metadata.update(rerank_score=final_score, intent=intent,
                                rewritten_query=rewritten)
            reranked.append((final_score, doc))
        return [doc for _, doc in sorted(reranked,
            key=lambda row: (-row[0], row[1].metadata['id']))[:self.k]]
