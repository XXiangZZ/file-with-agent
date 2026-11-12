"""Offline P0 regression; optional embeddings require --allow-model-calls.

All indexes are temporary. No production archive DB, model-based judge, or chat
generation is used. Ablations live here, not in the application's retriever.
"""
import argparse
import hashlib
import importlib.metadata
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from langsmith import tracing_context

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from assistant.generation import evidence_answer, verify_grounded_answer
from assistant.index import KnowledgeIndex
from assistant.manual import SCOPE, local_answer, normalize_question, prepare_manual
from assistant.parsing import Parser
from assistant.retrieval import ArchiveRetriever, latent_scores, rewrite_query, route_intent, bm25_scores
from assistant.tracing import traced, retrieval_event

METHODS = ('keyword', 'lsa_only', 'hybrid_no_rerank', 'hybrid', 'hybrid_filtered',
           'bm25_only', 'bm25_rrf_legacy', 'bm25_rrf_no_rerank', 'bm25_rrf')
DEFINITIONS = {
    'keyword': 'P0旧关键词基线 + 旧证据选择；含改写、意图过滤、字符余弦与规则重排',
    'lsa_only': '评测消融：同范围/改写/意图过滤，纯离线 TF-IDF/SVD LSA，不重排',
    'hybrid_no_rerank': '评测消融：当前 hybrid 候选按 retrieval_score 排序，不重排',
    'hybrid': 'P0旧hybrid + 旧证据选择：0.6 词面 + 0.4 LSA，然后规则重排',
    'hybrid_filtered': '同一hybrid检索 + 收紧本地证据选择（生产离线默认）',
    'bm25_only': '评测消融：BM25单路无重排 + 收紧证据选择',
    'bm25_rrf_legacy': '新BM25+LSA名次融合+规则重排 + 旧证据选择，隔离检索变化',
    'bm25_rrf_no_rerank': '评测消融：BM25+LSA名次融合不重排 + 收紧证据选择',
    'bm25_rrf': '可选生产检索：BM25+LSA名次融合+规则重排 + 收紧证据选择',
    'external_embeddings': '显式授权的当前词面/外部向量平均 + 规则重排；无聊天生成',
}


def identity(doc):
    return Path(doc.metadata['source']).name, doc.metadata['page']


def load_questions(path):
    questions = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(questions, list) or not questions:
        raise ValueError('评测题集不能为空')
    seen = set()
    for question in questions:
        if question['id'] in seen or question['task'] not in {'policy', 'manual'}:
            raise ValueError('题目ID重复或task无效')
        seen.add(question['id'])
        if not question['question'].strip() or not question['category'] or not question['scope']:
            raise ValueError('题目、分类与范围不能为空')
        for source, page, quote in question['gold']:
            if Path(source).name != source or not isinstance(page, int) or page < 1 or not quote:
                raise ValueError('gold必须为文件名、页码、必要原文片段')
    return questions


def prepare(index, embeddings=None):
    corpus, input_files = {}, []
    for path in sorted((ROOT / 'evaluation/fixtures/p0').glob('*.txt')):
        scope = '合同' if path.name == '合同规则.txt' else '文书'
        index.import_file(path, '规范', scope, embeddings=embeddings)
        input_files.append(path)
    prepare_manual(index, ROOT / 'archive_tool/resources/manual', embeddings=embeddings)
    input_files.extend(sorted((ROOT / 'archive_tool/resources/manual').glob('*.md')))
    for path in input_files:
        for doc in Parser().parse(path):
            key = identity(doc)
            if key in corpus:
                raise ValueError('来源文件名/页码冲突')
            corpus[key] = doc.page_content
    return corpus, input_files


def validate_gold(questions, corpus):
    for question in questions:
        for source, page, quote in question['gold']:
            if quote not in corpus.get((source, page), ''):
                raise ValueError(f"{question['id']} 的期望证据不存在: {source}:{page}: {quote}")


def retrieve(index, question, method, embeddings=None):
    query = normalize_question(question['question']) if question['task'] == 'manual' else question['question']
    kinds = ['手册'] if question['task'] == 'manual' else None
    if method in {'lsa_only', 'bm25_only'}:
        intent = route_intent(query)
        if kinds is None:
            kinds = ['手册'] if intent == 'manual' else ['规范'] if intent == 'field' else None
        docs = index.documents(question['scope'], kinds)
        if not docs:
            return []
        scores = (latent_scores if method == 'lsa_only' else bm25_scores)(rewrite_query(query), docs)
        ranked = sorted(zip(scores, docs), key=lambda row: (-row[0], row[1].metadata['id']))
        result = []
        for score, doc in ranked:
            if score > 0:
                doc.metadata['retrieval_score'] = score
                result.append(doc)
        return result[:4]
    # k=corpus size exposes all candidate scores without changing production code.
    # Top raw scores match the pre-rerank candidate prefix of the production path.
    raw = method in {'hybrid_no_rerank', 'bm25_rrf_no_rerank'}
    k = max(4, len(index.documents(question['scope'], kinds))) if raw else 4
    docs = ArchiveRetriever(index=index, scope=question['scope'], kinds=kinds,
        mode='keyword' if method == 'keyword' else 'bm25_rrf' if method.startswith('bm25_rrf') else 'hybrid', k=k,
        embeddings=embeddings if method == 'external_embeddings' else None).invoke(query)
    if raw:
        docs.sort(key=lambda doc: (-doc.metadata['retrieval_score'], doc.metadata['id']))
    return docs[:4]


def score_answer(question, docs, result, corpus):
    expected = {(source, page) for source, page, _ in question['gold']}
    keys = [identity(doc) for doc in docs]
    citations = result.get('citations', [])
    authentic, correct, support_passed, support_total = 0, 0, 0, 0
    covered = set()
    for cite in citations:
        key = Path(cite['source']).name, cite['page']
        quote = cite.get('quote', '')
        exists = bool(quote.strip()) and quote in corpus.get(key, '')
        authentic += int(exists)
        matched = {i for i, (source, page, fragment) in enumerate(question['gold'])
                   if key == (source, page) and fragment in quote and exists}
        correct += int(bool(matched))
        covered.update(matched)
        # Count actual displayed extractive content, never the stock answer banner.
        lines = quote.splitlines()
        if question['task'] == 'manual':
            import re
            lines = [line for line in lines if re.match(r'^\d+[.、]\s*\S', line)]
        for line in lines:
            if not line.strip():
                continue
            support_total += 1
            try:
                verify_grounded_answer({'answer': line, 'claims': [
                    {'text': line, 'citation_ids': [cite['id']]}]}, [cite])
                support_passed += int(exists)
            except (ValueError, TypeError, KeyError):
                pass
    return {'id': question['id'], 'category': question['category'],
            'question': question['question'], 'task': question['task'], 'scope': question['scope'],
            'answerable': bool(expected), 'gold': question['gold'],
            'retrieved': [{'source': identity(doc)[0], 'page': identity(doc)[1],
                           'score': doc.metadata.get('retrieval_score'),
                           'rerank_score': doc.metadata.get('rerank_score'),
                           'bm25_score': doc.metadata.get('bm25_score'),
                           'bm25_rank': doc.metadata.get('bm25_rank'),
                           'semantic_rank': doc.metadata.get('semantic_rank')} for doc in docs],
            'recall@1': len(expected & set(keys[:1])) / len(expected) if expected else None,
            'recall@3': len(expected & set(keys[:3])) / len(expected) if expected else None,
            'abstained': not bool(citations), 'citation_count': len(citations),
            'citation_authentic_count': authentic, 'citation_correct_count': correct,
            'support_passed': support_passed, 'support_total': support_total,
            'gold_covered': len(covered), 'gold_total': len(question['gold']),
            'answer': result['answer'],
            'citations': [{'source': Path(c['source']).name, 'page': c['page'], 'quote': c['quote']}
                          for c in citations]}


@traced('evaluation')
def evaluate_question(index, question, method, corpus, embeddings=None):
    with tracing_context(enabled=False):
        docs = retrieve(index, question, method, embeddings)
    retrieval_event(docs, method, 4)
    selection = 'focused' if method in {'hybrid_filtered', 'bm25_only', 'bm25_rrf_no_rerank', 'bm25_rrf'} else 'legacy'
    result = (local_answer if question['task'] == 'manual' else evidence_answer)(
        question['question'], docs, selection=selection)
    return score_answer(question, docs, result, corpus)


def metrics(rows):
    answerable = [row for row in rows if row['answerable']]
    unsupported = [row for row in rows if not row['answerable']]
    citations = sum(row['citation_count'] for row in rows)
    support = sum(row['support_total'] for row in rows)
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None
    return {'questions': len(rows), 'answerable': len(answerable), 'unsupported': len(unsupported),
        'recall@1': ratio(sum(row['recall@1'] for row in answerable), len(answerable)),
        'recall@3': ratio(sum(row['recall@3'] for row in answerable), len(answerable)),
        'citation_correctness': ratio(sum(row['citation_correct_count'] for row in rows), citations),
        'citation_authenticity': ratio(sum(row['citation_authentic_count'] for row in rows), citations),
        'unsupported_refusal_rate': ratio(sum(row['abstained'] for row in unsupported), len(unsupported)),
        'false_refusal_rate': ratio(sum(row['abstained'] for row in answerable), len(answerable)),
        'extractive_fact_support_pass_rate': ratio(sum(row['support_passed'] for row in rows), support),
        'all_gold_covered_rate': ratio(sum(row['gold_covered'] == row['gold_total'] for row in answerable), len(answerable)),
        'citation_count': citations, 'extractive_fact_count': support,
        'generated_claim_support_rate': None}


def comparison_details(rows):
    """Derive the review directly from scored rows; no hand-entered improvements."""
    old = {row['id']: row for row in rows if row['method'] == 'hybrid'}
    changes = {}
    for method in ('hybrid_filtered', 'bm25_rrf'):
        current = [row for row in rows if row['method'] == method]
        changes[method] = {
            'coverage_improved': [row['id'] for row in current if row['gold_covered'] > old[row['id']]['gold_covered']],
            'coverage_regressed': [row['id'] for row in current if row['gold_covered'] < old[row['id']]['gold_covered']],
            'recall1_improved': [row['id'] for row in current if row['answerable'] and row['recall@1'] > old[row['id']]['recall@1']],
            'recall1_regressed': [row['id'] for row in current if row['answerable'] and row['recall@1'] < old[row['id']]['recall@1']],
            'recall3_regressed': [row['id'] for row in current if row['answerable'] and row['recall@3'] < old[row['id']]['recall@3']],
            'remaining_incomplete': [row['id'] for row in current if row['answerable'] and row['gold_covered'] < row['gold_total']],
            'unsupported_not_refused': [row['id'] for row in current if not row['answerable'] and not row['abstained']],
        }
    audit = []
    for row in (row for row in rows if row['method'] == 'hybrid_filtered'):
        before = old[row['id']]
        removed = [cite for cite in before['citations'] if cite not in row['citations']]
        unmatched = [cite for cite in before['citations'] if not any(
            cite['source'] == source and cite['page'] == page and fragment in cite['quote']
            for source, page, fragment in row['gold'])]
        audit.append({'id': row['id'], 'category': row['category'],
                      'before_citations': before['citation_count'], 'after_citations': row['citation_count'],
                      'unmatched_before': unmatched, 'removed': removed,
                      'gold_before': before['gold_covered'], 'gold_after': row['gold_covered'],
                      'gold_total': row['gold_total']})
    return changes, audit


def markdown(report):
    def value(v):
        return 'N/A' if v is None else f'{v:.3f}'
    lines = ['# P0 脱敏离线回归', '',
             f"样本：{report['question_count']} 题；分类：{report['categories']}。开发者构造，不代表生产效果。",
             f"语料：{report['corpus']['files']} 个文件、{report['corpus']['pages']} 页、{report['corpus']['chunks']} 个片段；小库且题目共享条款，非独立业务样本。", '',
             '| 方法 | Recall@1 | Recall@3 | 引用正确率 | 引用真实性 | 拒答率 | 误拒答率 | 摘录支持通过率 | 必要证据全覆盖 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    keys = ('recall@1', 'recall@3', 'citation_correctness', 'citation_authenticity', 'unsupported_refusal_rate',
            'false_refusal_rate', 'extractive_fact_support_pass_rate', 'all_gold_covered_rate')
    for method, data in report['metrics'].items():
        lines.append('| ' + method + ' | ' + ' | '.join(value(data[key]) for key in keys) + ' |')
    if 'external_embeddings' not in report['metrics']:
        lines.append('| external_embeddings（未运行） | ' + ' | '.join(['N/A'] * len(keys)) + ' |')
    lines.extend(['', '外部嵌入：' + report['external_embeddings']['status'], '', '方法定义：', ''])
    lines.extend(f'- `{key}`：{definition}' for key, definition in DEFINITIONS.items())
    lines.extend(['', '指标定义与限制：', ''])
    lines.extend('- ' + item for item in report['limits'])
    lines.extend(['', '与旧hybrid相比的逐题变化（从结果自动生成）：', ''])
    for method, changes in report['changes'].items():
        lines.append(f'- `{method}`：{changes}')
    lines.extend(['', '默认过滤前后：按题目类别', '',
                  '| 类别 | 旧引用正确率 | 新引用正确率 | 旧全覆盖 | 新全覆盖 |',
                  '|---|---:|---:|---:|---:|'])
    for category, before in report['by_category']['hybrid'].items():
        after = report['by_category']['hybrid_filtered'][category]
        lines.append(f"| {category} | {value(before['citation_correctness'])} | {value(after['citation_correctness'])} | "
                     f"{value(before['all_gold_covered_rate'])} | {value(after['all_gold_covered_rate'])} |")
    lines.extend(['', '逐题证据选择审计（被过滤的原文在JSON的evidence_audit中）：', '',
                  '| 题号 | 旧引用数 | 新引用数 | 必要证据覆盖（旧→新/总数） |',
                  '|---|---:|---:|---|'])
    for audit in report['evidence_audit']:
        lines.append(f"| {audit['id']} | {audit['before_citations']} | {audit['after_citations']} | "
                     f"{audit['gold_before']}→{audit['gold_after']}/{audit['gold_total']} |")
    lines.extend(['', '逐题输出与分类指标见同目录 p0_results.json；任何低分均保留，不据此调优本次题集。', ''])
    return '\n'.join(lines)


def run(dataset=None, output_dir=None, *, allow_model_calls=False, config_path=None):
    dataset = Path(dataset or ROOT / 'evaluation/p0_questions.json')
    output_dir = Path(output_dir or ROOT / 'evaluation')
    questions = load_questions(dataset)
    embeddings = None
    if allow_model_calls:
        if config_path is None:
            raise ValueError('启用模型调用必须显式指定 --config')
        from assistant.services import ModelService, load_config
        config = load_config(config_path)
        if not config.get('embedding_model'):
            raise ValueError('嵌入模型未配置')
        embeddings = ModelService(config)
    elif config_path is not None:
        raise ValueError('--config 必须同时提供 --allow-model-calls')
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, summary, by_category = [], {}, {}
    with tempfile.TemporaryDirectory(prefix='archive-p0-') as temp:
        index = KnowledgeIndex(Path(temp) / 'knowledge.sqlite3')
        corpus, files = prepare(index)  # corpus/gold checks always finish before any network call
        validate_gold(questions, corpus)
        if embeddings is not None:
            prepare(index, embeddings)
        corpus_summary = {'files': len(files), 'pages': len(corpus),
            'chunks': sum(len(index.documents(scope)) for scope in ('文书', '合同', SCOPE)),
            'manifest': [{'file': str(path.relative_to(ROOT)).replace('\\', '/'),
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(files)]}
        for method in (*METHODS, *(['external_embeddings'] if embeddings is not None else [])):
            current = [dict(evaluate_question(index, question, method, corpus, embeddings,
                trace_path=output_dir / 'p0_traces.jsonl'), method=method) for question in questions]
            rows.extend(current)
            summary[method] = metrics(current)
            by_category[method] = {category: metrics([row for row in current if row['category'] == category])
                                   for category in sorted({row['category'] for row in current})}
    digest = hashlib.sha256(dataset.read_bytes())
    for path in sorted(files):
        digest.update(path.name.encode('utf-8'))
        digest.update(path.read_bytes())
    changes, audit = comparison_details(rows)
    report = {'schema_version': 2, 'dataset_sha256': digest.hexdigest(),
        'corpus': corpus_summary,
        'question_count': len(questions), 'categories': dict(Counter(q['category'] for q in questions)),
        'dependencies': {name: importlib.metadata.version(name) for name in
                         ('langchain-core', 'langchain-text-splitters', 'pydantic', 'numpy')},
        'external_embeddings': {'status': 'run' if embeddings else 'not_run_no_authorization',
                                'model': embeddings.embedding_model if embeddings else None},
        'chat_generation': 'not_run', 'methods': DEFINITIONS, 'metrics': summary,
        'changes': changes, 'evidence_audit': audit,
        'parameters': {'default_retrieval': 'hybrid', 'default_evidence': 'focused',
                       'chunk_size': 500, 'chunk_overlap': 80, 'top_k': 4,
                       'bm25_k1': 1.2, 'bm25_b': .75, 'rrf_k': 60,
                       'rrf_rerank_scale': '(rrf_k+1)/2', 'selection_score_margin': .05},
        'by_category': by_category, 'rows': rows,
        'limits': [
            f'{len(questions)}题为开发者合成/内置手册派生样本，无独立盲测，不代表生产效果；错字为人工注入，非OCR准确率。',
            'Recall按期望文件/页去重并仅对可回答题宏平均；多跳题Recall@1可能天然小于1；top-k只计算实际前k片段。',
            '引用正确率=来源页正确且引用包含至少一个标注必要片段的引用数/全部非空引用数；是严格标注匹配代理，不是语义裁判。',
            '引用真实性=逐字出处存在；空引用不进入引用分母；无样本指标为null而非1。',
            '拒答率=无引用的拒答题数/拒答题数，另报可回答题误拒答率；相关但不足的摘录也可能被此严格口径记作未拒答（如R08）。',
            '摘录事实支持通过率=展示摘录行通过逐字出处与现有claims token核验的比例；不验证问题适用性，复制原文的高通过率不是答案准确率。',
            '未运行聊天生成；生成事实句支持率为null。verify_grounded_answer不保证独立answer文本完全受claims覆盖，整段答案仍需独立审查。',
            '必要证据全覆盖只证明取到全部标注片段，不证明多跳推理完成、冲突效力被解决或任务成功。',
            '旧四组保留旧证据选择；新组显式标注过滤及重排，所有组共享范围/改写/意图过滤。LSA/BM25单路及无重排仅为评测消融。',
            '默认不构造模型服务；外部向量未运行即标N/A，模拟服务只验证调用/降级，不能冒充真实模型质量。',
        ]}
    (output_dir / 'p0_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output_dir / 'p0_comparison.md').write_text(markdown(report), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--allow-model-calls', action='store_true')
    parser.add_argument('--config', type=Path)
    arguments = parser.parse_args()
    run(arguments.dataset, arguments.output_dir, allow_model_calls=arguments.allow_model_calls,
        config_path=arguments.config)
