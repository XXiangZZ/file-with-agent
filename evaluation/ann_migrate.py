"""Build/check a SciPy ANN sidecar from existing authorized SQLite vectors.

No embedding requests. Does not edit the SQLite database or delete its vectors.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from assistant.index import KnowledgeIndex


def migrate(path, scope, model, *, kinds=None, eps=.15):
    path = Path(path).resolve(strict=True)
    # Refuse archive.db/non-knowledge databases before opening KnowledgeIndex,
    # whose initializer would otherwise create tables in an unrelated DB.
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'sources', 'chunks', 'vectors', 'feedback'} <= tables or 'records' in tables:
            raise ValueError('请选择知识库数据库，不能迁移档案业务库')
    index = KnowledgeIndex(path)
    rows = index.vector_rows(scope, kinds, expected_model=model)
    if not rows or any(vector is None for _, vector in rows):
        raise ValueError('范围内没有完整的当前模型向量；不调用服务补齐')
    def digest():
        with path.open('rb') as source:
            return hashlib.file_digest(source, 'sha256').hexdigest()
    before = digest()
    started = perf_counter()
    result = index.ann_search(scope, kinds, rows[0][1], model, min(4, len(rows)), eps)
    if digest() != before:
        raise RuntimeError('迁移期间权威SQLite发生变化，请重新构建')
    return {'backend': 'scipy.cKDTree', 'scope': scope, 'model': model,
            'vectors': len(rows), 'dimensions': len(rows[0][1]), 'eps': eps,
            'build_ms': (perf_counter() - started) * 1000,
            'sample_neighbors': [doc.metadata['id'] for doc in result],
            'sqlite_unchanged': True, 'sidecar': path.name + '.ann',
            'limits': ['近似树在高维可能接近线性扫描；必须用真实向量另测召回和性能。',
                       '侧车NPZ保存可重建归一化快照，cKDTree在进程内重建；不是FAISS/HNSW。']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--scope', required=True)
    parser.add_argument('--model', required=True, help='与SQLite vectors.model完全一致，含服务身份')
    parser.add_argument('--kind', nargs='+')
    parser.add_argument('--eps', type=float, default=.15)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db, args.scope, args.model, kinds=args.kind, eps=args.eps), ensure_ascii=False, indent=2))
