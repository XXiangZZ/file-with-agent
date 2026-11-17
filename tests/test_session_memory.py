import json
import pytest
from assistant.agent.runner import run_agent
from assistant.agent.session import AgentSession
from assistant.index import KnowledgeIndex


class Service:
    chat_model = 'fake'
    embedding_model = ''
    model_name = 'fake'
    config = {'chat_model': 'fake'}
    def __init__(self):
        self.payloads = []
    def post(self, route, payload):
        self.payloads.append(payload)
        if payload['messages'][-1]['role'] == 'user':
            return {'choices': [{'message': {'content': '', 'tool_calls': [
                {'id': f'call-{len(self.payloads)}', 'function': {'name': 'kb_sources', 'arguments': '{}'}}]}}]}
        text = '知识库共有 0 份资料。'
        return {'choices': [{'message': {'content': json.dumps({'answer': text, 'claims': [
            {'text': text, 'citation_ids': ['kb-source-count']}]}, ensure_ascii=False)}}]}


def test_memory_is_bounded_history_not_current_evidence_and_clears_on_scope_change(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    service, session = Service(), AgentSession(max_turns=2)
    for query in ('查看知识库', '再查一次', '确认当前资料数'):
        result = run_agent(query, index, service, allow_model_calls=True, session=session, template_name='文书')
        assert result['answer_verified']
    assert len(session.turns) == 2
    latest = service.payloads[-2]['messages']
    assert any('previous_verified_answer' in message['content'] for message in latest)
    assert all('tool_calls' not in message for message in latest if 'previous_verified_answer' in message['content'])
    run_agent('切换范围', index, service, allow_model_calls=True, session=session, template_name='合同')
    assert len(session.turns) == 1
    session.clear()
    assert session.turns == [] and session.plan_store is None


def test_memory_pending_and_approved_plan_block_new_round_and_clearing(tmp_path):
    from types import SimpleNamespace
    session = AgentSession()
    for status in ('pending', 'approved'):
        session.plan_store = SimpleNamespace(plans={'p': SimpleNamespace(status=status)})
        with pytest.raises(RuntimeError, match='计划'):
            session.clear()
        with pytest.raises(RuntimeError, match='计划'):
            run_agent('新问题', KnowledgeIndex(tmp_path / 'kb.sqlite3'), Service(), allow_model_calls=True, session=session)
    session.plan_store.plans['p'].status = 'rejected'
    session.clear()


def test_expiry_concurrency_unverified_output_and_revision_change_clear_memory(tmp_path, monkeypatch):
    import assistant.agent.session as memory
    now = [0.]
    monkeypatch.setattr(memory, 'monotonic', lambda: now[0])
    session = AgentSession(ttl=5)
    session.begin('scope')
    with pytest.raises(RuntimeError):
        session.begin('scope')
    session.finish('问题', {'answer_verified': False, 'answer': '未核验敏感正文'})
    assert session.turns == []
    session._running = False
    session.turns = [('old', 'old')]
    now[0] = 6
    session.begin('scope')
    assert not session.turns
    session._running = False
    index, service = KnowledgeIndex(tmp_path / 'kb.sqlite3'), Service()
    run_agent('查询', index, service, allow_model_calls=True, session=session)
    path = tmp_path / 'rules.txt'
    path.write_text('题名：照录原文。', encoding='utf-8')
    index.import_file(path, '规范', '文书')
    # Beginning a changed index context must discard previous source assertions.
    session.begin((str(index.path), index.revision()))
    assert session.turns == []
    session._running = False
