"""Tiny manual QA evaluation, local only. Independent of archive data."""
import json
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from assistant.index import KnowledgeIndex
from assistant.manual import prepare_manual, ask_manual, normalize_question, SCOPE
from assistant.retrieval import ArchiveRetriever


def run():
    questions = json.loads((ROOT / 'evaluation/manual_questions.json').read_text(encoding='utf-8'))
    rows, metrics = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        index = KnowledgeIndex(Path(tmp) / 'manual.sqlite3')
        prepare_manual(index, ROOT / 'archive_tool/resources/manual')
        for mode in ('keyword', 'hybrid'):
            recall = {1: [], 3: []}
            for question in questions:
                docs = ArchiveRetriever(index=index, scope=SCOPE, kinds=['手册'], mode=mode, k=3).invoke(
                    normalize_question(question['question']))
                names = [Path(doc.metadata['source']).name for doc in docs]
                if question['expected']:
                    for k in (1, 3):
                        recall[k].append(int(question['expected'] in names[:k]))
                result = ask_manual(index, question['question'], mode=mode)
                verified = all(c['quote'] in Path(c['source']).read_text(encoding='utf-8') for c in result['citations'])
                rows.append({'id': question['id'], 'mode': mode, 'question': question['question'],
                    'expected': question['expected'], 'retrieved': names,
                    'abstained': not bool(result['citations']), 'citation_text_verified': verified,
                    'answer': result['answer'],
                    'citations': [{**c, 'source': str(Path(c['source']).relative_to(ROOT)).replace('\\', '/')}
                                  for c in result['citations']]})
            metrics[mode] = {f'recall@{k}': sum(values) / len(values) for k, values in recall.items()}
    result = {'dataset': '9 authored manual questions, 7 answerable, 2 unsupported',
        'models': 'local extractive mode; no model or external embeddings invoked',
        'metrics': metrics, 'rows': rows,
        'limits': ['Small authored set, not independent production evaluation.',
                   'Both baselines use the same explicit query aliases.',
                   'Citation text existence is not semantic correctness.',
                   'Unsupported questions excluded from Recall denominator.']}
    (ROOT / 'evaluation/manual_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))
    print('Unsupported abstentions:', sum(r['abstained'] for r in rows if not r['expected']), '/ 4 mode-question pairs')


if __name__ == '__main__':
    run()
