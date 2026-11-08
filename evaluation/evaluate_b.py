"""Run the synthetic B-tier RAG evaluation without external model calls."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))

from assistant.generation import ask
from assistant.index import KnowledgeIndex
from assistant.retrieval import ArchiveRetriever, tokens


def run():
    fixture = ROOT / 'evaluation' / 'fixtures'
    questions = json.loads((ROOT / 'evaluation' / 'questions.json').read_text(encoding='utf-8'))
    corpus = {}
    rows, metrics = [], {}
    with tempfile.TemporaryDirectory(prefix='archive-b-eval-') as temp:
        index = KnowledgeIndex(Path(temp) / 'knowledge.sqlite3')
        for path in sorted(fixture.glob('*.txt')):
            kind = {'sample.txt': '样例', 'manual.txt': '手册'}.get(path.name, '规范')
            scope = '合同' if path.name == 'contract.txt' else '文书'
            index.import_file(path, kind, scope)
        docs = index.documents('文书')
        corpus = {(Path(doc.metadata['source']).name, doc.metadata['page']): doc.page_content
                  for doc in docs}
        for mode in ('keyword', 'hybrid'):
            recalls = {1: [], 3: []}
            citation_authentic, citation_count = 0, 0
            answer_relevance, aligned_quotes = [], []
            refusals, unsupported_count = 0, 0
            for question in questions:
                expected = {tuple(item) for item in question['expected']}
                retrieved = ArchiveRetriever(index=index, scope='文书', mode=mode, k=3).invoke(
                    question['question'])
                retrieved_ids = [(Path(doc.metadata['source']).name, doc.metadata['page'])
                                 for doc in retrieved]
                if expected:
                    for k in (1, 3):
                        recalls[k].append(len(expected & set(retrieved_ids[:k])) / len(expected))
                else:
                    unsupported_count += 1
                result = ask(index, question['question'], '文书', mode)
                citations = result['citations']
                if not expected and not citations:
                    refusals += 1
                query_terms = set(tokens(question['question'], True))
                row_authentic, row_aligned = [], []
                for cite in citations:
                    citation_count += 1
                    key = (Path(cite['source']).name, cite['page'])
                    authentic = cite['quote'] in corpus.get(key, '')
                    aligned = key in expected and authentic
                    citation_authentic += int(authentic)
                    row_authentic.append(authentic)
                    row_aligned.append(aligned)
                    quote_terms = set(tokens(cite['quote'], True))
                    answer_relevance.append(len(query_terms & quote_terms) / max(1, len(query_terms)))
                if expected:
                    aligned_quotes.extend(row_aligned or [False])
                rows.append({
                    'mode': mode, 'id': question['id'],
                    'intent': retrieved[0].metadata.get('intent') if retrieved else None,
                    'retrieved': retrieved_ids,
                    'rerank_scores': [doc.metadata.get('rerank_score') for doc in retrieved],
                    'expected': sorted(expected),
                    'citations_authentic': row_authentic,
                    'citations_source_aligned': row_aligned,
                    'abstained': not bool(citations),
                    'model_used': result.get('model_used', False),
                    'answer': result['answer'],
                })
            metrics[mode] = {
                'recall@1': sum(recalls[1]) / len(recalls[1]),
                'recall@3': sum(recalls[3]) / len(recalls[3]),
                'answer_relevance_token_overlap_proxy': sum(answer_relevance) / len(answer_relevance)
                    if answer_relevance else None,
                'faithfulness_source_alignment_proxy': sum(aligned_quotes) / len(aligned_quotes)
                    if aligned_quotes else None,
                'unsupported_refusal_rate': refusals / unsupported_count if unsupported_count else None,
                'citation_authenticity_rate': citation_authentic / citation_count
                    if citation_count else None,
                'citation_count': citation_count,
            }
    output = {
        'dataset': '7 developer-authored synthetic questions; 6 answerable, 1 unsupported',
        'models': 'local only; no chat model or external embeddings called',
        'pipeline': 'query rewrite -> intent routing -> hybrid candidates -> local rerank -> extractive answer',
        'metrics': metrics,
        'rows': rows,
        'metric_definitions': {
            'answer_relevance_token_overlap_proxy': 'Question-token overlap with cited quotes; lexical proxy, not semantic judge.',
            'faithfulness_source_alignment_proxy': 'Cited quote occurs in an expected source/page; provenance proxy, not entailment.',
            'citation_authenticity_rate': 'Exact quote substring exists on the cited indexed source/page.',
            'unsupported_refusal_rate': 'No citation returned for the authored unsupported question.',
        },
        'limits': ['Small authored test set; not a production quality estimate.',
                   'Semantic faithfulness and answer relevance require blind human or independent model review.',
                   'No real model participated.'],
    }
    output_path = ROOT / 'evaluation' / 'b_results.json'
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f'Results: {output_path}')


if __name__ == '__main__':
    run()
