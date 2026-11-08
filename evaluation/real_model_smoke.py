"""Explicitly authorized two-path real-model acceptance test using synthetic text."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))

from assistant.index import KnowledgeIndex
from assistant.manual import SCOPE, ask_manual
from assistant.generation import ask
from assistant.services import ModelService, load_config


def run(config_path, allow_model_calls):
    if not allow_model_calls:
        raise SystemExit('No model request sent. Re-run with --allow-model-calls to authorize requests.')
    config = load_config(config_path)
    if not config.get('chat_model') or not config.get('embedding_model'):
        raise SystemExit('Configure chat_model and embedding_model in assistant.local.json or environment first.')
    service = ModelService(config)
    fixture = ROOT / 'evaluation' / 'fixtures' / 'sanitized_manual.md'
    with tempfile.TemporaryDirectory(prefix='archive-rag-smoke-') as temp:
        index = KnowledgeIndex(Path(temp) / 'knowledge.sqlite3')
        manual_import = index.import_file(fixture, kind='手册', scope=SCOPE, embeddings=service)
        manual_vectors = index.vector_rows(SCOPE, ['手册'], expected_model=service.model_name)
        manual_result = ask_manual(index, '如何导出档案？', service=service, use_embeddings=True)
        manual_text = fixture.read_text(encoding='utf-8')
        manual_citations_verified = bool(manual_result['citations']) and all(
            citation['quote'] in manual_text for citation in manual_result['citations'])

        rules_path = Path(temp) / 'sanitized_rules.txt'
        rules_text = '文件题名：应照录原文标题，不得自行增补。\n文件日期：按原文日期著录，不得猜测。\n'
        rules_path.write_text(rules_text, encoding='utf-8')
        rules_import = index.import_file(rules_path, kind='规范', scope='文书', embeddings=service)
        rules_vectors = index.vector_rows('文书', ['规范'], expected_model=service.model_name)
        rules_result = ask(index, '文件题名如何填写？', '文书',
                           embeddings=service, service=service)
        rules_citations_verified = bool(rules_result['citations']) and all(
            citation['quote'] in rules_text for citation in rules_result['citations'])

        if (not manual_vectors or any(vector is None for _, vector in manual_vectors) or
                not rules_vectors or any(vector is None for _, vector in rules_vectors)):
            raise RuntimeError('Persistent embedding verification failed')
        if (not manual_result.get('model_used') or not manual_citations_verified or
                not rules_result.get('model_used') or not rules_citations_verified):
            diagnostics = {
                'manual': {'model_used': manual_result.get('model_used'),
                           'mode': manual_result.get('mode'),
                           'citation_count': len(manual_result.get('citations', [])),
                           'notice': manual_result.get('notice')},
                'policy': {'model_used': rules_result.get('model_used'),
                           'mode': rules_result.get('mode'),
                           'citation_count': len(rules_result.get('citations', [])),
                           'notice': rules_result.get('notice'),
                           'fallback_reason': rules_result.get('fallback_reason')},
            }
            raise RuntimeError('Real-model QA path check failed: ' +
                               json.dumps(diagnostics, ensure_ascii=False))
        report = {
            'real_models_used': True,
            'chat_model': config['chat_model'],
            'embedding_model': config['embedding_model'],
            'steps': ['manual_import_and_embedding', 'manual_hybrid_retrieval_and_generation',
                      'policy_import_and_embedding', 'policy_hybrid_retrieval_and_generation',
                      'citation_source_checks'],
            'manual_path': {
                'question': '如何导出档案？', 'import': manual_import,
                'vector_count': sum(vector is not None for _, vector in manual_vectors),
                'citation_count': len(manual_result['citations']),
                'citations_verified_against_fixture': manual_citations_verified,
                'answer_mode': manual_result['mode'],
            },
            'policy_path': {
                'question': '文件题名如何填写？', 'import': rules_import,
                'vector_count': sum(vector is not None for _, vector in rules_vectors),
                'citation_count': len(rules_result['citations']),
                'citations_verified_against_fixture': rules_citations_verified,
                'answer_mode': rules_result.get('mode'),
            },
            'limits': ['Synthetic sanitized manual and policy only; no archive data used.',
                       'Quote identity is checked; semantic faithfulness still requires human review.'],
        }
        report_path = ROOT / 'evaluation' / 'real_model_acceptance.json'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        report['report_path'] = str(report_path.relative_to(ROOT)).replace('\\', '/')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path,
                        default=ROOT / 'archive_tool' / 'config' / 'assistant.local.json')
    parser.add_argument('--allow-model-calls', action='store_true')
    args = parser.parse_args()
    run(args.config, args.allow_model_calls)
