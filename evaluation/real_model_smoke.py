"""Explicitly authorized OpenAI-compatible/Ollama smoke test; uses synthetic manual text."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))

from assistant.index import KnowledgeIndex
from assistant.manual import SCOPE, ask_manual
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
        imported = index.import_file(fixture, kind='手册', scope=SCOPE, embeddings=service)
        vectors = index.vector_rows(SCOPE, ['手册'])
        result = ask_manual(index, '如何导出档案？', service=service, use_embeddings=True)
        source_text = fixture.read_text(encoding='utf-8')
        citations_verified = bool(result['citations']) and all(
            citation['quote'] in source_text for citation in result['citations'])
        if not vectors or any(vector is None for _, vector in vectors):
            raise RuntimeError('Persistent embedding verification failed')
        if not result.get('model_used') or not citations_verified:
            raise RuntimeError('Real model chain did not complete with verified source quotes')
        report = {
            'real_models_used': True,
            'chat_model': config['chat_model'],
            'embedding_model': config['embedding_model'],
            'steps': ['import', 'persisted_embeddings', 'hybrid_retrieval', 'chat_generation', 'quote_source_check'],
            'import': imported,
            'vector_count': sum(vector is not None for _, vector in vectors),
            'citation_count': len(result['citations']),
            'citations_verified_against_fixture': citations_verified,
            'answer_mode': result['mode'],
            'limits': ['Synthetic sanitized manual only; no archive data used.',
                       'Quote identity is checked; semantic faithfulness still requires human review.'],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path,
                        default=ROOT / 'archive_tool' / 'config' / 'assistant.local.json')
    parser.add_argument('--allow-model-calls', action='store_true')
    args = parser.parse_args()
    run(args.config, args.allow_model_calls)
