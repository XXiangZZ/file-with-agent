"""No actual sleeps or model requests in transport guard regression."""
import json
from urllib.error import HTTPError, URLError

import pytest

from assistant import services, runtime
from assistant.services import ModelService
from assistant.runtime import task_budget, BudgetExceeded, CircuitOpen
from assistant.generation import ask
from assistant.index import KnowledgeIndex


class Response:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return b'{"usage":{"total_tokens":9},"choices":[{"message":{"content":"{}"}}]}'


def service(**config):
    return ModelService({'chat_model': 'fake', 'chat_base_url': 'http://localhost/v1',
                         'retry_backoff': 0, **config})


@pytest.mark.parametrize('failure', [TimeoutError(), URLError('offline'),
    HTTPError('http://localhost', 429, 'private body', {'Retry-After': '0'}, None),
    HTTPError('http://localhost', 503, 'private body', {}, None)])
def test_transient_retry_count_usage_and_max_output(monkeypatch, failure):
    calls, pauses = [], []
    def request(req, timeout):
        calls.append((json.loads(req.data), timeout))
        if len(calls) == 1:
            raise failure
        return Response()
    monkeypatch.setattr(services, 'urlopen', request)
    monkeypatch.setattr(services, 'sleep', pauses.append)
    current = service(max_output_tokens=64)
    with task_budget(current.config) as budget:
        current.post('/chat/completions', {'messages': []})
        assert budget.requests == 2
        assert budget.reported_tokens == 9
        assert budget.reserved_tokens > 128
    assert len(calls) == 2 and len(pauses) == 1
    assert calls[0][0]['max_tokens'] == 64


@pytest.mark.parametrize('failure', [
    HTTPError('http://localhost', 401, 'do-not-leak', {}, None),
    HTTPError('http://localhost', 400, 'do-not-leak', {}, None), ValueError('invalid json')])
def test_permanent_errors_never_retry(monkeypatch, failure):
    calls = []
    def request(*args, **kwargs):
        calls.append(True)
        raise failure
    monkeypatch.setattr(services, 'urlopen', request)
    monkeypatch.setattr(services, 'sleep', lambda _: pytest.fail('must not back off'))
    with pytest.raises(RuntimeError, match='模型服务不可用') as error:
        service().post('/chat/completions', {})
    assert 'do-not-leak' not in str(error.value)
    assert len(calls) == 1


def test_breaker_blocks_then_recovers_without_sleep(monkeypatch):
    now = [0.]
    monkeypatch.setattr(services, 'monotonic', lambda: now[0])
    calls = []
    def request(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise TimeoutError()
        return Response()
    monkeypatch.setattr(services, 'urlopen', request)
    current = service(max_retries=0, breaker_threshold=1, breaker_cooldown=5)
    with pytest.raises(RuntimeError):
        current.post('/chat/completions', {})
    with pytest.raises(CircuitOpen):
        current.post('/chat/completions', {})
    assert len(calls) == 1
    now[0] = 6
    current.post('/chat/completions', {})
    current.post('/chat/completions', {})
    assert len(calls) == 3


def test_shared_budget_blocks_retries_and_nested_embedding_calls(monkeypatch):
    calls = []
    def request(*args, **kwargs):
        calls.append(True)
        raise TimeoutError()
    monkeypatch.setattr(services, 'urlopen', request)
    monkeypatch.setattr(services, 'sleep', lambda _: None)
    current = service(max_requests=1)
    with task_budget(current.config) as budget:
        with pytest.raises(BudgetExceeded, match='请求次数'):
            current.post('/chat/completions', {})
        assert budget.requests == 1
        with task_budget({}) as nested:
            assert nested is budget
            with pytest.raises(BudgetExceeded):
                current.post('/chat/completions', {})
    assert len(calls) == 1 and runtime._budget.get() is None


def test_deadline_sets_socket_timeout_and_rejects_long_retry_after(monkeypatch):
    now = [0.]
    monkeypatch.setattr(runtime, 'monotonic', lambda: now[0])
    def request(req, timeout):
        assert timeout <= 2
        now[0] += 3
        return Response()
    monkeypatch.setattr(services, 'urlopen', request)
    current = service(task_timeout=2)
    with pytest.raises(BudgetExceeded, match='总时间'):
        current.post('/chat/completions', {})
    now[0] = 0
    def limited(*args, **kwargs):
        raise HTTPError('http://localhost', 429, '', {'Retry-After': '60'}, None)
    monkeypatch.setattr(services, 'urlopen', limited)
    monkeypatch.setattr(services, 'sleep', lambda _: pytest.fail('no long blocking wait'))
    with pytest.raises(BudgetExceeded, match='退避'):
        service().post('/chat/completions', {})


def test_token_and_optional_money_guards_prevent_requests(monkeypatch):
    monkeypatch.setattr(services, 'urlopen', lambda *a, **k: pytest.fail('budget must block before network'))
    with pytest.raises(BudgetExceeded, match='token'):
        service(max_task_tokens=1).post('/chat/completions', {})
    with pytest.raises(BudgetExceeded, match='价格'):
        service(max_task_cost=1).post('/chat/completions', {})
    with pytest.raises(BudgetExceeded, match='金额'):
        service(max_task_cost=.000001, input_price_per_million=1,
                output_price_per_million=1).post('/chat/completions', {})


def test_budget_failure_retains_local_rag_fallback(tmp_path, monkeypatch):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    text = tmp_path / 'rules.txt'
    text.write_text('题名：照录原文标题。', encoding='utf-8')
    index.import_file(text, '规范', '文书')
    monkeypatch.setattr(services, 'urlopen', lambda *a, **k: pytest.fail('token gate'))
    result = ask(index, '题名如何填写', '文书', service=service(max_task_tokens=1))
    assert result['citations'] and not result['model_used']
    assert 'BudgetExceeded' in result['fallback_reason']
    assert runtime._budget.get() is None


@pytest.mark.parametrize('config', [{'max_retries': 1.5}, {'max_retries': 4},
    {'retry_backoff': float('nan')}, {'task_timeout': -1}, {'max_requests': 1.5}])
def test_guard_config_validation(config):
    with pytest.raises(ValueError):
        current = service(**config)
        with task_budget(current.config):
            pass
