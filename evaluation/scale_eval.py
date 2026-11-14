"""Reproducible synthetic local index benchmark, no model/production DB access."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
from time import perf_counter
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from langsmith import tracing_context
import numpy as np
from assistant.index import KnowledgeIndex, VERSION
from assistant.retrieval import ArchiveRetriever, latent_scores
from langchain_core.documents import Document


class SyntheticVectors:
    model_name = 'synthetic-benchmark-vector'
    def __init__(self, dimensions):
        self.vector = np.ones(dimensions, dtype=float).tolist()
    def embed_query(self, text):
        return self.vector


def measure(function, repeats):
    timings = []
    for _ in range(repeats):
        start = perf_counter()
        function()
        timings.append((perf_counter() - start) * 1000)
    return {'repeats': repeats, 'p50_ms': statistics.median(timings),
            'p95_ms': float(np.percentile(timings, 95)), 'samples_ms': timings}


def benchmark(count, dimensions=64, repeats=5):
    if count < 1 or dimensions < 1 or repeats < 1:
        raise ValueError('规模、维度、重复数必须为正数')
    rng = np.random.default_rng(42)
    with tempfile.TemporaryDirectory(prefix='archive-scale-') as temp:
        start = perf_counter()
        index = KnowledgeIndex(Path(temp) / 'kb.sqlite3')
        with index.connect() as db:
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?)',
                       ('synthetic-benchmark.txt', 'synthetic', '规范', '文书', 'synthetic-time', VERSION))
            for i in range(count):
                scope = '文书' if i % 10 == 0 else '合同'
                metadata = {'id': f'chunk-{i:08}', 'source': 'synthetic-benchmark.txt',
                    'page': i + 1, 'kind': '规范', 'scope': scope, 'start_index': 0}
                text = ('题名照录原文；日期缺失不得猜测。责任者按署名单位填写。' * 6) + f' 分类{i % 20}'
                db.execute('INSERT INTO chunks VALUES (?,?,?,?)',
                           (metadata['id'], metadata['source'], text, json.dumps(metadata, ensure_ascii=False)))
                vector = rng.normal(size=dimensions).tolist()
                db.execute('INSERT INTO vectors VALUES (?,?,?,?)',
                           (metadata['id'], json.dumps(vector), SyntheticVectors.model_name, dimensions))
        build_ms = (perf_counter() - start) * 1000
        # Query only 10% of chunks, exposing the current all-rows load overhead.
        with tracing_context(enabled=False):
            docs_timing = measure(lambda: index.documents('文书', ['规范']), repeats)
            vector_timing = measure(lambda: index.vector_rows('文书', ['规范'], SyntheticVectors.model_name), repeats)
            retriever = ArchiveRetriever(index=index, scope='文书', embeddings=SyntheticVectors(dimensions), k=4)
            retrieval_timing = measure(lambda: retriever.invoke('文件题名如何填写'), repeats)
        tracemalloc.start()
        with tracing_context(enabled=False):
            retriever.invoke('文件题名如何填写')
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {'chunks': count, 'selected_scope_chunks': (count + 9) // 10, 'dimensions': dimensions,
            'build_ms': build_ms, 'sqlite_bytes': index.path.stat().st_size,
            'documents': docs_timing, 'vector_rows': vector_timing, 'exact_hybrid_retrieval': retrieval_timing,
            'python_peak_tracemalloc_bytes': peak}


def run(output_dir=None, sizes=(100, 1000, 10000), dimensions=64, repeats=5):
    rows = []
    for size in sizes:
        row = benchmark(size, dimensions, repeats)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    # Separate SVD compute from vector path. No pretending this covers 10k LSA.
    docs = [Document(page_content=('题名日期责任者档案草稿导入导出校验' * 3) + f' 分组{i % 30}') for i in range(200)]
    lsa = measure(lambda: latent_scores('文件题名如何填写', docs), repeats)
    report = {'seed': 42, 'python': sys.version.split()[0], 'numpy': np.__version__,
        'rows': rows, 'lsa_200_chunks_recompute': lsa,
        'limits': ['合成片段和随机64维向量，不是语义效果测试，不发嵌入请求，不代表真实模型维度或分布。',
            'P95仅5次样本的插值，暖文件缓存、单进程串行；无并发/锁等待/冷启动或百万级实测结论。',
            '峰值为tracemalloc追踪的Python分配，不等同于整个进程RSS或NumPy原生内存。',
            '索引用批量SQL建立在临时KnowledgeIndex，不包含解析/OCR/远程嵌入构建成本；实际查询走生产documents/vector_rows/ArchiveRetriever。',
            'LSA只单测200片段；其SVD每次重算，未把此小样本耗时外推至大库。']}
    output_dir = Path(output_dir or ROOT / 'evaluation/scale')
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'scale_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--sizes', type=int, nargs='+', default=[100, 1000, 10000])
    parser.add_argument('--dimensions', type=int, default=64)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    run(args.output_dir, args.sizes, args.dimensions, args.repeats)
