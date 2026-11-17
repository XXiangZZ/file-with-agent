import asyncio
import json
from pathlib import Path
import threading
import httpx
import pytest
from langchain_core.prompts import ChatPromptTemplate

from assistant.async_http import AsyncModelService, SSEMessage
from assistant.async_api import arun_agent, aask
from assistant.services import ModelService
from assistant.index import KnowledgeIndex
from assistant.runtime import task_budget, BudgetExceeded

CONFIG = {'chat_base_url': 'http://localhost/v1', 'chat_model': 'fake',
          'embedding_base_url': 'http://localhost/v1', 'embedding_model': '', 'retry_backoff': 0}


def sse(*deltas):
    events = ['data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': None}]}, ensure_ascii=False)
              + '\n\n' for delta in deltas]
    events.append('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'tool_calls'
        if any('tool_calls' in delta for delta in deltas) else 'stop'}]}) + '\n\n')
    events.append('data: [DONE]\n\n')
    return ''.join(events).encode('utf-8')


class Bytes(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.closed = False
    async def __aiter__(self):
        # Arbitrary UTF-8 and line boundaries, not one JSON per TCP read.
        for i in range(0, len(self.data), 13):
            await asyncio.sleep(0)
            yield self.data[i:i + 13]
    async def aclose(self):
        self.closed = True


def test_sse_tool_arguments_buffered_until_done_and_invalid_end_rejected():
    assembler = SSEMessage()
    for delta in [ {'tool_calls': [{'index': 0, 'id': 'one', 'function': {'name': 'ask_', 'arguments': '{"ques'}}]},
                   {'tool_calls': [{'index': 0, 'function': {'name': 'policy', 'arguments': 'tion":"题名"}'}}]} ]:
        assembler.feed(json.dumps({'choices': [{'delta': delta}]}))
    with pytest.raises(ValueError, match='中断'):
        assembler.result()
    assembler.feed(json.dumps({'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]}))
    assembler.feed('[DONE]')
    call = assembler.result()['choices'][0]['message']['tool_calls'][0]
    assert call['function']['name'] == 'ask_policy'
    assert json.loads(call['function']['arguments']) == {'question': '题名'}
    with pytest.raises(ValueError):
        assembler.feed('[DONE]')
    truncated = SSEMessage()
    with pytest.raises(ValueError, match='完整'):
        truncated.feed(json.dumps({'choices': [{'delta': {}, 'finish_reason': 'length'}]}))


def test_native_async_http_sse_unicode_progress_and_embedding_validation():
    async def run():
        progress = []
        event_thread = threading.get_ident()
        async def handler(request):
            assert threading.get_ident() == event_thread
            if request.url.path.endswith('/embeddings'):
                return httpx.Response(200, json={'data': [{'index': 0, 'embedding': [1., 0.]}]})
            assert json.loads(request.content)['stream']
            return httpx.Response(200, headers={'Content-Type': 'text/event-stream'},
                stream=Bytes(sse({'content': '题名'}, {'content': '：照录原文。'})))
        async with AsyncModelService({**CONFIG, 'embedding_model': 'fake'},
                transport=httpx.MockTransport(handler), progress=progress.append) as service:
            prompt = ChatPromptTemplate.from_messages([('human', '题名')]).format_prompt()
            text, vectors = await asyncio.gather(service.complete_prompt(prompt), service.embed_query('题名'))
            assert text == '题名：照录原文。' and vectors == [1., 0.]
            assert progress and all(set(item) == {'type', 'chars'} for item in progress)
            assert not any('照录' in str(item) for item in progress)
        assert service._client is None
    asyncio.run(run())


def test_async_cancellation_closes_stream_and_does_not_retry():
    async def run():
        started = asyncio.Event()
        attempts = []
        class Slow(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                started.set()
                await asyncio.sleep(60)
                yield b''
            async def aclose(self):
                self.closed = True
        stream = Slow()
        async def handler(request):
            attempts.append(True)
            return httpx.Response(200, stream=stream)
        async with AsyncModelService(CONFIG, transport=httpx.MockTransport(handler)) as service:
            task = asyncio.create_task(service.post('/chat/completions', {}, stream=True))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert stream.closed and len(attempts) == 1
    asyncio.run(run())


def test_async_retry_shared_budget_and_deadline_are_enforced():
    async def run():
        calls = []
        async def handler(request):
            calls.append(True)
            return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={'usage': {'total_tokens': 2}})
        async with AsyncModelService(CONFIG, transport=httpx.MockTransport(handler)) as service:
            with task_budget({**CONFIG, 'max_requests': 2}) as budget:
                await service.post('/chat/completions', {})
                assert budget.requests == 2
                with pytest.raises(BudgetExceeded):
                    await service.post('/chat/completions', {})
        async def slow(request):
            await asyncio.sleep(.2)
            return httpx.Response(200, json={})
        async with AsyncModelService({**CONFIG, 'task_timeout': .01, 'max_retries': 0},
                transport=httpx.MockTransport(slow)) as service:
            with pytest.raises(RuntimeError):
                await service.post('/chat/completions', {})
    asyncio.run(run())


def test_partial_stream_is_discarded_without_retry_or_tool_execution():
    async def run():
        calls = []
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                raise httpx.ReadError('synthetic disconnection')
        async def handler(request):
            calls.append(True)
            return httpx.Response(200, stream=Broken())
        async with AsyncModelService({**CONFIG, 'max_retries': 3}, transport=httpx.MockTransport(handler)) as service:
            with pytest.raises(RuntimeError, match='不可用'):
                await service.post('/chat/completions', {}, stream=True)
        assert len(calls) == 1
    asyncio.run(run())


def test_async_agent_two_streamed_turns_verify_before_return_and_preserve_tool_ids(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    async def run():
        calls = []
        progress = []
        async def handler(request):
            payload = json.loads(request.content)
            calls.append(payload)
            if len(calls) == 1:
                data = sse({'tool_calls': [{'index': 0, 'id': 'one', 'function': {
                    'name': 'kb_sources', 'arguments': '{}'}}]})
            else:
                assert payload['messages'][-2]['tool_calls'][0]['id'] == 'one'
                assert payload['messages'][-1]['tool_call_id'] == 'one'
                result = {'answer': '知识库共有 0 份资料。并已上传全部档案。', 'claims': [
                    {'text': '知识库共有 0 份资料。', 'citation_ids': ['kb-source-count']}]}
                text = json.dumps(result, ensure_ascii=False)
                data = sse({'content': text[:15]}, {'content': text[15:]})
            return httpx.Response(200, stream=Bytes(data))
        result = await arun_agent('查看知识库', index, ModelService(CONFIG), allow_model_calls=True,
            transport=httpx.MockTransport(handler), progress=progress.append)
        assert result['answer_verified'] and '上传' not in result['answer']
        assert result['coverage']['rewritten'] and result['request_budget']['requests'] == 2
        assert any(event['type'] == 'model_turn' for event in progress)
        assert not any('上传' in str(event) for event in progress)
    asyncio.run(run())


def test_unauthorized_async_agent_never_creates_transport(tmp_path, monkeypatch):
    import assistant.async_api as api
    monkeypatch.setattr(api, 'AsyncModelService', lambda *a, **k: pytest.fail('unauthorized transport construction'))
    result = asyncio.run(api.arun_agent('查询', KnowledgeIndex(tmp_path / 'kb.sqlite3'),
        service=object(), allow_model_calls=False, local_tool='kb_sources'))
    assert not result['model_used']


def test_native_async_loopback_http_stream_does_not_block_event_loop():
    async def run():
        body = sse({'content': '异步'}, {'content': '成功'})
        async def handle(reader, writer):
            try:
                head = await reader.readuntil(b'\r\n\r\n')
                size = next(int(line.split(b':', 1)[1]) for line in head.split(b'\r\n') if line.lower().startswith(b'content-length:'))
                await reader.readexactly(size)
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\nContent-Length: ' +
                             str(len(body)).encode() + b'\r\n\r\n')
                await writer.drain()
                for offset in range(0, len(body), 20):
                    writer.write(body[offset:offset + 20])
                    await writer.drain()
                    await asyncio.sleep(.002)
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        ticks = []
        async def heartbeat():
            for _ in range(10):
                ticks.append(True)
                await asyncio.sleep(.002)
        try:
            async with AsyncModelService({**CONFIG, 'chat_base_url': f'http://127.0.0.1:{port}/v1'}) as service:
                reply, _ = await asyncio.gather(service.post('/chat/completions', {}, stream=True), heartbeat())
                assert reply['choices'][0]['message']['content'] == '异步成功'
                assert len(ticks) == 10
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_cancelling_async_agent_preserves_pending_plan_without_writes(tmp_path):
    sys_path = str(Path(__file__).resolve().parents[1] / 'evaluation')
    import sys
    sys.path.insert(0, sys_path)
    import agent_eval
    from assistant.agent.session import AgentSession
    with agent_eval.sandbox(tmp_path) as context:
        before = agent_eval.snapshot()
        async def run():
            second = asyncio.Event()
            calls = []
            session = AgentSession()
            async def handler(request):
                calls.append(True)
                if len(calls) == 1:
                    args = {'record_id': context['record_id']}
                    return httpx.Response(200, stream=Bytes(sse({'tool_calls': [{'index': 0, 'id': 'plan',
                        'function': {'name': 'propose_mark_reviewed', 'arguments': json.dumps(args)}}]})))
                second.set()
                await asyncio.sleep(60)
                return httpx.Response(200, json={})
            task = asyncio.create_task(arun_agent('仅提标记核对计划', KnowledgeIndex(tmp_path / 'kb.sqlite3'),
                ModelService(CONFIG), allow_model_calls=True, session=session,
                record_manager=context['records'], draft_manager=context['drafts'], template_manager=context['templates'],
                batch_id=context['batch_id'], template_name='文书', transport=httpx.MockTransport(handler)))
            await second.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not session._running and len(session.plan_store.get_pending()) == 1
            assert session.plan_store.get_pending()[0].status == 'pending'
        asyncio.run(run())
        assert agent_eval.snapshot() == before
