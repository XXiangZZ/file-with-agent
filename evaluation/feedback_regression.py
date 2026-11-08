"""Replay saved negative/failure samples against the current local retrieval chain."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))

from assistant.generation import ask
from assistant.index import KnowledgeIndex
from assistant.retrieval import tokens


def run(database):
    index = KnowledgeIndex(database)
    samples = index.feedback_samples(needs_review=True)
    rows, authentic, citations, abstentions, relevance = [], 0, 0, 0, []
    for sample in samples:
        result = ask(index, sample['question'], sample['scope'])
        sample_authentic = []
        query_terms = set(tokens(sample['question'], True))
        for cite in result['citations']:
            source = Path(cite['source'])
            try:
                content = source.read_text(encoding='utf-8')
                valid = cite['quote'] in content
            except (OSError, UnicodeError):
                valid = False
            citations += 1
            authentic += int(valid)
            sample_authentic.append(valid)
            quote_terms = set(tokens(cite['quote'], True))
            relevance.append(len(query_terms & quote_terms) / max(1, len(query_terms)))
        abstentions += int(not result['citations'])
        rows.append({'feedback_id': sample['id'], 'failure': sample['failure'],
                     'previously_helpful': sample['helpful'],
                     'has_correction': bool(sample['correction']),
                     'correction': sample['correction'],
                     'previous_answer': sample['answer'],
                     'citation_authenticity': sample_authentic,
                     'abstained': not bool(result['citations']),
                     'answer': result['answer']})
    report = {
        'sample_count': len(samples),
        'citation_authenticity_rate': authentic / citations if citations else None,
        'answer_relevance_token_overlap_proxy': sum(relevance) / len(relevance) if relevance else None,
        'abstention_rate': abstentions / len(samples) if samples else None,
        'corrections_requiring_human_review': sum(bool(s['correction']) for s in samples),
        'rows': rows,
        'limits': ['Saved queries are replayed locally with current sources.',
                   'Correction text is shown for human comparison; semantic correctness is not auto-scored.'],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path,
                        default=ROOT / 'archive_tool' / 'data' / 'knowledge.sqlite3')
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f'Feedback database not found: {args.db}')
    run(args.db)
