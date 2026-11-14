"""Local traces must not expose archive content or change control boundaries."""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError

import pytest

from assistant.agent.runner import run_agent
from assistant.generation import ask
from assistant.index import KnowledgeIndex
from assistant.manual import SCOPE, ask_manual
from assistant.services import ModelService


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


class ScriptedService:
    config = {'chat_model': 'fake'}
    chat_model = 'fake'
    embedding_model = ''

    def __init__(self, responses):
        self.responses = iter(responses)

    def post(self, route, payload):
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def tool(name, arguments):
    return {'choices': [{'message': {'content': '', 'tool_calls': [
        {'id': 'call-1', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}]}


def final(content):
    return {'choices': [{'message': {'content': content}}]}


def test_agent_trace_links_nested_rag_and_redacts_question_arguments_results(tmp_path):
    secret = '绝不落盘的用户原文S3CRET'
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    source = tmp_path / '私有文件名.txt'
    source.write_text('文件题名：照录标题。' + secret, encoding='utf-8')
    index.import_file(source, '规范', '文书')
    path = tmp_path / 'trace.jsonl'
    service = ScriptedService([tool('ask_policy', {'question': '题名' + secret, 'scope': '文书'}),
        final(json.dumps({'answer': '证据不足', 'claims': []}, ensure_ascii=False))])
    result = run_agent('题名' + secret, index, service, allow_model_calls=True, trace_path=path)
    assert result['model_used']
    raw = path.read_text(encoding='utf-8')
    assert secret not in raw and source.name not in raw and str(source) not in raw
    events = rows(path)
    assert len({event['run_id'] for event in events}) == 1
    assert {event['event'] for event in events} >= {'tool_start', 'tool_end', 'retrieval', 'model_turn_end', 'verification'}
    assert next(event for event in events if event['event'] == 'tool_start')['tool'] == 'ask_policy'
    starts = [event for event in events if event['event'] == 'model_turn_start']
    assert [event['turn'] for event in starts] == [1, 2]
    assert [event['seq'] for event in events] == list(range(1, len(events) + 1))


def test_unauthorized_agent_never_calls_service_and_is_not_recorded_as_fallback(tmp_path):
    class Forbidden:
        def post(self, *args):
            raise AssertionError('unauthorized model request')
    path = tmp_path / 'local.jsonl'
    result = run_agent('查询', KnowledgeIndex(tmp_path / 'kb.sqlite3'), Forbidden(),
                       allow_model_calls=False, local_tool='kb_sources', trace_path=path)
    assert not result['model_used']
    events = rows(path)
    assert not any(event['event'].startswith('model_') for event in events)
    assert events[-1]['fallback'] is False


def test_unknown_and_invalid_tools_do_not_log_model_supplied_content(tmp_path):
    secret = '机密模型工具名及参数'
    path = tmp_path / 'invalid.jsonl'
    service = ScriptedService([tool(secret, {'name': secret}),
        tool('get_record_detail', {'record_id': secret}), final('非法JSON' + secret),
        final('仍然非法JSON' + secret)])
    result = run_agent(secret, KnowledgeIndex(tmp_path / 'kb.sqlite3'), service,
                       allow_model_calls=True, trace_path=path)
    assert '隐藏' in result['verified_answer']
    assert secret not in path.read_text(encoding='utf-8')
    events = rows(path)
    assert any(event.get('error_type') == 'tool_not_allowed' for event in events)
    assert any(event.get('error_type') == 'ValidationError' for event in events)
    assert any(event['event'] == 'verification' and not event['passed'] for event in events)


def test_rag_manual_fallbacks_and_transport_error_classification(tmp_path, monkeypatch):
    import assistant.services as services
    secret = '密钥响应正文和档案字段'
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    source = tmp_path / 'rule.txt'
    source.write_text('文件题名：照录原文标题。', encoding='utf-8')
    index.import_file(source, '规范', '文书')
    manual = tmp_path / 'manual.md'
    manual.write_text('# 导出\n1. 点击导出，选择批次。', encoding='utf-8')
    index.import_file(manual, '手册', SCOPE)
    def timeout(*args, **kwargs):
        raise TimeoutError(secret)
    monkeypatch.setattr(services, 'urlopen', timeout)
    service = ModelService({'chat_model': 'fake', 'chat_base_url': 'http://localhost/v1'})
    path = tmp_path / 'fallback.jsonl'
    result = ask(index, '文件题名如何填写', '文书', service=service, trace_path=path)
    assert not result['model_used'] and result['citations']
    result = ask_manual(index, '如何导出', service=service, trace_path=path)
    assert not result['model_used'] and '退回' in result['notice']
    events = rows(path)
    assert any(event.get('category') == 'timeout' for event in events)
    assert {event.get('stage') for event in events if event['event'] == 'fallback'} == {'policy', 'manual_generation'}
    assert secret not in path.read_text(encoding='utf-8')

    def unauthorized(*args, **kwargs):
        raise HTTPError('http://localhost/' + secret, 401, secret, {}, None)
    monkeypatch.setattr(services, 'urlopen', unauthorized)
    # Earlier repeated transient errors now open the circuit. A fresh service
    # isolates the non-retryable HTTP case; circuit behavior has separate tests.
    service = ModelService({'chat_model': 'fake', 'chat_base_url': 'http://localhost/v1'})
    with pytest.raises(RuntimeError):
        service.post('/chat/completions', {'messages': [{'content': secret}]}, trace_path=path)
    assert any(event.get('category') == 'http' for event in rows(path))
    assert secret not in path.read_text(encoding='utf-8')


def test_transport_success_keeps_only_numeric_usage_and_never_credentials(tmp_path, monkeypatch):
    import assistant.services as services
    secret = 'credential-and-response-secret'
    monkeypatch.setenv('TRACE_TEST_API_KEY', secret)
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({'choices': [{'message': {'content': secret}}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15,
                          'untrusted_key': secret}}).encode('utf-8')
    def fake_urlopen(request, timeout):
        assert request.get_header('Authorization') == 'Bearer ' + secret
        return Response()
    monkeypatch.setattr(services, 'urlopen', fake_urlopen)
    service = ModelService({'chat_model': 'fake', 'chat_base_url': 'http://localhost/v1',
                            'api_key_env': 'TRACE_TEST_API_KEY'})
    path = tmp_path / 'transport.jsonl'
    result = service.post('/chat/completions', {'messages': [{'content': secret}]}, trace_path=path)
    assert result['choices'][0]['message']['content'] == secret
    assert secret not in path.read_text(encoding='utf-8')
    response = next(event for event in rows(path) if event['event'] == 'model_response')
    assert response['usage'] == {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15}


def test_jsonl_concurrent_runs_rotate_and_unwritable_logs_do_not_change_answers(tmp_path, monkeypatch):
    import assistant.tracing as tracing
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    path = tmp_path / 'shared.jsonl'
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: ask(index, '无匹配问题', trace_path=path), range(8)))
    assert all(not result['citations'] for result in results)
    events = rows(path)
    assert len({event['run_id'] for event in events}) == 8
    for run_id in {event['run_id'] for event in events}:
        sequence = [event['seq'] for event in events if event['run_id'] == run_id]
        assert sequence == list(range(1, len(sequence) + 1))
    monkeypatch.setattr(tracing, 'MAX_BYTES', 1500)
    for _ in range(3):
        ask(index, '无匹配问题', trace_path=path)
    assert path.stat().st_size <= 1500
    assert path.with_suffix('.jsonl.1').stat().st_size <= 1500
    assert rows(path) and rows(path.with_suffix('.jsonl.1'))
    # Passing an existing directory produces an I/O error, swallowed by diagnostics.
    assert ask(index, '无匹配问题', trace_path=tmp_path)['citations'] == []
    assert tmp_path.is_dir() and index.path.is_file()
    assert tracing._current.get() is None


def test_model_failure_retains_pending_plan_without_any_business_writes(tmp_path, monkeypatch):
    from core.template_manager import TemplateManager
    from db import database
    database.close_connection()
    monkeypatch.setattr(database, 'DATABASE_PATH', tmp_path / 'archive.db')
    try:
        database.init_database()
        templates = TemplateManager()
        templates.init_database_templates()
        template_id = templates.get_template_id('文书')
        key = templates.get_fields('文书')[0]['key']
        with database.get_cursor() as cursor:
            cursor.execute('INSERT INTO batches(name,template_id,template_name) VALUES(?,?,?)',
                           ('脱敏批次', template_id, '文书'))
            batch_id = cursor.lastrowid
        def counts():
            with database.get_cursor() as cursor:
                return [cursor.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                        for table in ('records', 'drafts', 'operation_log')]
        before = counts()
        secret = '机密字段及名称不应进入轨迹'
        path = tmp_path / 'pending.jsonl'
        service = ScriptedService([tool('propose_create_record', {
            'name': secret, 'batch_id': batch_id, 'template_name': '文书', 'data': {key: secret}}),
            RuntimeError(secret)])
        result = run_agent(secret, KnowledgeIndex(tmp_path / 'kb.sqlite3'), service,
            allow_model_calls=True, template_manager=templates, batch_id=batch_id,
            template_name='文书', local_tool='kb_sources', trace_path=path)
        assert len(result['plans']) == 1 and result['plans'][0]['status'] == 'pending'
        assert len(result['_plan_store'].get_pending()) == 1
        assert counts() == before
        assert any(event.get('stage') == 'agent' and event['pending_plans'] == 1 for event in rows(path))
        assert secret not in path.read_text(encoding='utf-8')
    finally:
        database.close_connection()
