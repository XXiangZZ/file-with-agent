"""Reproducible, tiny synthetic retrieval evaluation. No external calls."""
import json
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from assistant.index import KnowledgeIndex
from assistant.retrieval import ArchiveRetriever
from assistant.generation import ask, suggest


def run():
    fixture = ROOT / 'evaluation' / 'fixtures'
    questions = json.loads((ROOT / 'evaluation' / 'questions.json').read_text(encoding='utf-8'))
    rows, metrics = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        index = KnowledgeIndex(Path(tmp) / 'kb.sqlite3')
        for path in sorted(fixture.glob('*.txt')):
            index.import_file(path, {'sample.txt': '样例', 'manual.txt': '手册'}.get(path.name, '规范'),
                              '合同' if path.name == 'contract.txt' else '文书')
        for mode in ('keyword', 'hybrid'):
            recalls = {1: [], 3: []}
            for question in questions:
                docs = ArchiveRetriever(index=index, scope='文书', mode=mode, k=3).invoke(question['question'])
                expected = {tuple(x) for x in question['expected']}
                retrieved = [(Path(d.metadata['source']).name, d.metadata['page']) for d in docs]
                values = {}
                for k in (1, 3):
                    if expected:
                        recall = len(expected & set(retrieved[:k])) / len(expected)
                        recalls[k].append(recall)
                        values[f'recall@{k}'] = recall
                answer = ask(index, question['question'], '文书', mode)
                all_docs = index.documents('文书')
                exact = all(any(c['source'] == d.metadata['source'] and c['page'] == d.metadata['page']
                                and c['quote'] in d.page_content for d in all_docs) for c in answer['citations'])
                rows.append({'mode': mode, 'id': question['id'], 'retrieved': retrieved,
                             **values, 'citation_text_verified': exact,
                             'abstained': not bool(answer['citations']),
                             'answer': answer})
            metrics[mode] = {f'macro_recall@{k}': sum(v)/len(v) for k, v in recalls.items()}
        from assistant.parsing import Parser
        fields = [{'key': 'title', 'name': '题名'}, {'key': 'date', 'name': '日期'}, {'key': 'author', 'name': '责任者'}]
        suggestions = suggest(Parser().parse(fixture / 'sample.txt'), fields)
    result = {'dataset': '7 synthetic questions, 6 answerable; no production-quality inference',
              'semantic_method': 'local TF-IDF/SVD LSA with synonym expansion; no pretrained embeddings',
              'metrics': metrics, 'rows': rows, 'suggestions': suggestions,
              'limits': ['Recall uses expected source/page and macro averages answerable questions only.',
                         'Citation substring checks prove provenance, not semantic support. See human_review.md.',
                         'OCR errors are injected text, not measured OCR accuracy.',
                         'External chat/embedding services not evaluated.']}
    output = ROOT / 'evaluation' / 'results.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f'Results: {output}')


if __name__ == '__main__':
    run()
