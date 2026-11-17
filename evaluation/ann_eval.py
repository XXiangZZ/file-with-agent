"""ANN migration and neighbor-recall benchmark on a disposable knowledge DB."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from assistant.index import KnowledgeIndex, VERSION
from ann_migrate import migrate


def percentile(times):
    return {'p50_ms': float(np.percentile(times, 50)), 'p95_ms': float(np.percentile(times, 95)), 'samples_ms': times}


def benchmark(count=10000, dimensions=32, queries=20):
    rng = np.random.default_rng(42)
    vectors = rng.normal(size=(count, dimensions)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    query_vectors = rng.normal(size=(queries, dimensions)).astype(np.float32)
    query_vectors /= np.linalg.norm(query_vectors, axis=1, keepdims=True)
    with tempfile.TemporaryDirectory(prefix='archive-ann-bench-') as temp:
        index = KnowledgeIndex(Path(temp) / 'kb.sqlite3')
        source = 'synthetic.txt'
        model = 'synthetic#32d'
        with index.connect() as db:
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?)', (source, 'synthetic', '规范', '文书', 'synthetic', VERSION))
            for i, vector in enumerate(vectors):
                meta = {'id': f'c-{i:06}', 'source': source, 'page': i + 1, 'kind': '规范', 'scope': '文书'}
                db.execute('INSERT INTO chunks VALUES (?,?,?,?)', (meta['id'], source, '题名照录原文。', json.dumps(meta)))
                db.execute('INSERT INTO vectors VALUES (?,?,?,?)', (meta['id'], json.dumps(vector.tolist()), model, dimensions))
        migration = migrate(index.path, '文书', model)
        # Warm only the ANN cache once; exact reference reads SQLite per query,
        # matching the old persisted-vector materialization path.
        index.ann_search('文书', None, query_vectors[0], model, 4)
        ann_times, exact_times, recalls = [], [], []
        for query in query_vectors:
            started = perf_counter()
            rows = index.vector_rows('文书', None, expected_model=model)
            matrix = np.asarray([vector for _, vector in rows], dtype=np.float32)
            matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
            exact_ids = {rows[int(i)][0].metadata['id'] for i in np.argsort(-(matrix @ query))[:4]}
            exact_times.append((perf_counter() - started) * 1000)
            started = perf_counter()
            results = index.ann_search('文书', None, query, model, 4, .15)
            ann_times.append((perf_counter() - started) * 1000)
            recalls.append(len(exact_ids & {doc.metadata['id'] for doc in results}) / 4)
        report = {'backend': 'scipy.cKDTree', 'seed': 42, 'chunks': count, 'dimensions': dimensions,
            'queries': queries, 'eps': .15, 'neighbor_recall_at_4': sum(recalls) / len(recalls),
            'recall_samples': recalls, 'ann_warm_queries': percentile(ann_times),
            'exact_with_sqlite_materialization': percentile(exact_times), 'migration': migration,
            'limits': ['随机合成向量，邻居召回不是RAG回答效果；32维结果不能外推至高维预训练嵌入。',
                'ANN查询包含SQL范围/模型/版本检查与缓存使用；首次建树另计，SQLite读取/向量加载差异是加速来源之一。',
                '不是ANN与完全同缓存条件下矩阵乘法的公平算法竞速；高维cKDTree可能退化，默认hybrid未替换。',
                '20次暖缓存、单线程样本；未测百万级、并发、冷缓存；模型服务/OCR均不参与。']}
    return report


def run(output_dir=None, **kwargs):
    report = benchmark(**kwargs)
    output_dir = Path(output_dir or ROOT / 'evaluation/ann')
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'ann_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--count', type=int, default=10000)
    parser.add_argument('--dimensions', type=int, default=32)
    parser.add_argument('--queries', type=int, default=20)
    args = parser.parse_args()
    run(args.output_dir, count=args.count, dimensions=args.dimensions, queries=args.queries)
