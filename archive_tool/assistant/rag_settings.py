"""Request-time local RAG switches; no file, database or model access."""
import os


def evidence_mode():
    value = os.environ.get('ARCHIVE_RAG_EVIDENCE', 'focused')
    if value not in {'legacy', 'focused'}:
        raise ValueError('ARCHIVE_RAG_EVIDENCE 必须为 legacy 或 focused')
    return value


def retrieval_mode():
    value = os.environ.get('ARCHIVE_RAG_RETRIEVAL', 'hybrid')
    if value not in {'keyword', 'hybrid', 'bm25_rrf'}:
        raise ValueError('ARCHIVE_RAG_RETRIEVAL 必须为 keyword、hybrid 或 bm25_rrf')
    return value
