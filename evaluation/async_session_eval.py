"""Local HTTP/SSE + real Agent/session smoke; never contacts external models."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from assistant.services import ModelService
from assistant.async_api import arun_agent
from assistant.agent.session import AgentSession
from assistant.index import KnowledgeIndex


async def exercise():
    payloads, events, received = [], [], []
    def packet(delta, finish=None):
        return ('data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]}, ensure_ascii=False) + '\n\n').encode('utf-8')
    async def handler(reader, writer):
        try:
            headers = await reader.readuntil(b'\r\n\r\n')
            size = next(int(line.split(b':', 1)[1]) for line in headers.split(b'\r\n') if line.lower().startswith(b'content-length:'))
            payload = json.loads(await reader.readexactly(size))
            payloads.append(payload)
            if payload['messages'][-1]['role'] == 'user':
                data = packet({'tool_calls': [{'index': 0, 'id': f'call-{len(payloads)}',
                    'function': {'name': 'kb_sources', 'arguments': '{'}}]})
                data += packet({'tool_calls': [{'index': 0, 'function': {'arguments': '}'}}]})
                data += packet({}, 'tool_calls')
            else:
                tool_result = json.loads(payload['messages'][-1]['content'])
                evidence = tool_result['citations'][0]
                raw = json.dumps({'answer': evidence['quote'], 'claims': [
                    {'text': evidence['quote'], 'citation_ids': [evidence['id']]}]}, ensure_ascii=False)
                data = packet({'content': raw[:25]}) + packet({'content': raw[25:]}) + packet({}, 'stop')
            data += b'data: [DONE]\n\n'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\nContent-Length: ' +
                         str(len(data)).encode() + b'\r\n\r\n')
            await writer.drain()
            for i in range(0, len(data), 37):
                writer.write(data[i:i + 37])
                await writer.drain()
                await asyncio.sleep(.002)
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(handler, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with tempfile.TemporaryDirectory(prefix='archive-async-eval-') as temp:
            index = KnowledgeIndex(Path(temp) / 'kb.sqlite3')
            rules = Path(temp) / 'rules.txt'
            rules.write_text('题名：照录原文。', encoding='utf-8')
            index.import_file(rules, '规范', '文书')
            service = ModelService({'chat_model': 'synthetic-local-server',
                'chat_base_url': f'http://127.0.0.1:{port}/v1'})
            session = AgentSession()
            answers = []
            started = perf_counter()
            for question in ('查看知识库资料数', '再确认一下刚才的数量'):
                result = await arun_agent(question, index, service, allow_model_calls=True,
                    session=session, template_name='文书', progress=events.append)
                answers.append({'verified': result['answer_verified'], 'answer': result['answer'],
                    'session_turns': result['session_turns'], 'requests': result['request_budget']['requests']})
            # No payloads/raw SSE are persisted; only booleans and synthetic checked answers.
            second_question = payloads[2]['messages']
            report = {'external_model_calls': 0, 'local_http_requests': len(payloads),
                'stream_progress_events': sum(event['type'] == 'receiving' for event in events),
                'progress_contains_body': any('照录' in str(event) or 'citation_ids' in str(event) for event in events),
                'memory_present_on_followup': any('previous_verified_answer' in message['content'] for message in second_question),
                'all_answers_verified': all(answer['verified'] for answer in answers), 'answers': answers,
                'elapsed_ms': (perf_counter() - started) * 1000,
                'limits': ['本机合成OpenAI兼容HTTP服务，证明异步/SSE/会话贯通，不证明真实厂商SSE兼容性或多轮指代能力。',
                    '不读取生产archive.db；只读kb_sources，无计划执行；网络仅127.0.0.1回环。']}
            return report
    finally:
        server.close()
        await server.wait_closed()


def run(output_dir=None):
    report = asyncio.run(exercise())
    output_dir = Path(output_dir or ROOT / 'evaluation/async_ann_memory')
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'async_session_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    run(args.output_dir)
