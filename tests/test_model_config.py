import json
from pathlib import Path

from assistant.index import KnowledgeIndex
from assistant.manual import SCOPE, ask_manual
from assistant.generation import ask
from assistant.services import ModelService, load_config


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'evaluation' / 'fixtures' / 'sanitized_manual.md'


def test_config_file_and_environment_overrides(tmp_path):
    config_path = tmp_path / 'assistant.local.json'
    config_path.write_text(json.dumps({
        'chat_base_url': 'http://127.0.0.1:11434/v1',
        'chat_model': 'chat-from-file',
        'embedding_model': 'embedding-from-file',
        'chat_api_key_env': 'CHAT_KEY',
    }), encoding='utf-8')
    config = load_config(config_path, {
        'ARCHIVE_CHAT_MODEL': 'chat-from-env',
        'ARCHIVE_EMBEDDING_BASE_URL': 'http://localhost:11434/v1',
        'ARCHIVE_EMBEDDING_API_KEY_ENV': 'EMBED_KEY',
        'ARCHIVE_MODEL_TIMEOUT': '12',
    })
    assert config['chat_model'] == 'chat-from-env'
    assert config['embedding_model'] == 'embedding-from-file'
    assert config['embedding_base_url'].startswith('http://localhost')
    assert config['embedding_api_key_env'] == 'EMBED_KEY'
    assert config['timeout'] == '12'
    assert 'api_key' not in config


def test_model_service_uses_distinct_local_endpoints_and_timeout(monkeypatch):
    import assistant.services as services

    calls = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"data":[{"index":0,"embedding":[1.0,0.0]}]}'

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr(services, 'urlopen', fake_urlopen)
    service = ModelService({
        'chat_base_url': 'http://localhost:11434/v1', 'chat_model': 'chat',
        'embedding_base_url': 'http://127.0.0.1:11435/v1', 'embedding_model': 'embed',
        'timeout': 8,
    })
    assert service.embed_documents(['synthetic text']) == [[1.0, 0.0]]
    assert calls == [('http://127.0.0.1:11435/v1/embeddings', 8)]


def test_mock_full_import_embedding_retrieval_generation_and_quote_check(tmp_path, monkeypatch):
    service = ModelService({
        'chat_base_url': 'http://localhost:11434/v1', 'chat_model': 'mock-chat',
        'embedding_base_url': 'http://localhost:11434/v1', 'embedding_model': 'mock-embed',
    })
    calls = []

    def mock_post(route, payload):
        calls.append(route)
        if route == '/embeddings':
            return {'data': [{'index': i, 'embedding': [1.0, 0.0]}
                             for i, _ in enumerate(payload['input'])]}
        prompt = payload['messages'][1]['content']
        evidence_json = prompt.split('手册证据：', 1)[1]
        evidence = json.loads(evidence_json)
        cite = next(item for item in evidence if item['source'].endswith('sanitized_manual.md'))
        quote = next(line for line in cite['quote'].splitlines() if line.startswith('2.'))
        answer = {'steps': [{'id': cite['id'], 'quote': quote}]}
        return {'choices': [{'message': {'content': json.dumps(answer, ensure_ascii=False)}}]}

    monkeypatch.setattr(service, 'post', mock_post)
    index = KnowledgeIndex(tmp_path / 'knowledge.sqlite3')
    result = index.import_file(FIXTURE, kind='手册', scope=SCOPE, embeddings=service)
    assert '向量' not in result
    assert all(vector is not None for _, vector in index.vector_rows(SCOPE, ['手册']))
    answer = ask_manual(index, '如何导出档案？', service=service, use_embeddings=True)
    assert answer['model_used'] is True
    assert answer['citations'][0]['quote'].startswith('2.')
    assert answer['citations'][0]['quote'] in FIXTURE.read_text(encoding='utf-8')
    assert calls.count('/embeddings') == 2  # Document chunks and the query vector.
    assert calls.count('/chat/completions') == 1


def test_rag_model_and_embedding_failures_return_local_answer(tmp_path, monkeypatch):
    index = KnowledgeIndex(tmp_path / 'knowledge.sqlite3')
    source = tmp_path / 'rule.txt'
    source.write_text('文件题名：按原文著录。', encoding='utf-8')
    index.import_file(source, scope='文书')
    service = ModelService({
        'chat_base_url': 'http://localhost:11434/v1', 'chat_model': 'mock-chat',
        'embedding_base_url': 'http://localhost:11434/v1', 'embedding_model': 'mock-embed',
    })

    def unavailable(*args, **kwargs):
        raise RuntimeError('offline')

    monkeypatch.setattr(service, 'complete_prompt', unavailable)
    chat_fallback = ask(index, '文件题名怎么填写', '文书', service=service)
    assert chat_fallback['citations'] and not chat_fallback['model_used']
    assert '退回本地' in chat_fallback['notice']

    embedding_fallback = ask(index, '文件题名怎么填写', '文书',
                              embeddings=service, service=service)
    assert embedding_fallback['citations'] and not embedding_fallback['model_used']
    assert '退回本地' in embedding_fallback['notice']
