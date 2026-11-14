import json
import pytest
from assistant.agent.runner import run_agent, _verify_agent_answer
from assistant.agent.tools import build_tools
from assistant.index import KnowledgeIndex


def test_metadata_numbers_status_and_refusal_cannot_be_paraphrased():
    cite = {'id': 'db-1', 'kind': '数据库', 'quote': '批次 1 共有 2 条记录；本次最多展示 100 条。'}
    for text in ('批次 1 共有 3 条记录', '批次 2 共有 2 条记录', '数据库总共只有2条记录'):
        raw = {'answer': text, 'claims': [{'text': text, 'citation_ids': ['db-1']}]}
        with pytest.raises(ValueError, match='逐字'):
            _verify_agent_answer(json.dumps(raw, ensure_ascii=False), [cite])
    text = '批次 1 共有 2 条记录'
    assert _verify_agent_answer(json.dumps({'answer': text, 'claims': [
        {'text': text, 'citation_ids': ['db-1']}]}, ensure_ascii=False), [cite])['claims']


def test_context_and_one_format_repair_stay_inside_four_turn_limit(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    rules = tmp_path / 'rules.txt'
    rules.write_text('题名：照录原文。', encoding='utf-8')
    index.import_file(rules, '规范', '文书')
    class Service:
        config = {'chat_model': 'fake'}
        chat_model = 'fake'
        def __init__(self):
            self.calls = 0
        def post(self, route, payload):
            self.calls += 1
            system = payload['messages'][0]['content']
            assert 'policy_scopes' in system and '文书' in system and 'current_batch_id' in system
            assert payload['response_format'] == {'type': 'json_object'}
            if self.calls == 1:
                return {'choices': [{'message': {'content': 'plain final'}}]}
            assert payload['messages'][-1]['content'].startswith('格式纠正：')
            return {'choices': [{'message': {'content': '{"answer":"证据不足","claims":[]}'}}]}
    service = Service()
    result = run_agent('查询', index, service, allow_model_calls=True, template_name='文书', batch_id=7)
    assert service.calls == 2
    assert result['answer_verified'] and not result['verified_claims']


def test_kb_sources_has_safe_count_citation_and_policy_uses_current_scope(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    rules = tmp_path / 'private-source.txt'
    rules.write_text('题名：照录原文。', encoding='utf-8')
    index.import_file(rules, '规范', '文书')
    tools, _ = build_tools(index, template_name='文书')
    by_name = {tool.name: tool for tool in tools}
    result = json.loads(by_name['ask_policy'].invoke({'question': '题名如何填写'}))
    assert result['citations']
    raw = by_name['kb_sources'].invoke({})
    assert str(tmp_path) not in raw
    result = json.loads(raw)
    assert result['citations'][0]['quote'] == '知识库共有 1 份资料。'


def test_invalid_explicit_record_id_never_calls_any_model_or_changes_target(tmp_path):
    class Forbidden:
        config = {'chat_model': 'fake'}
        def post(self, *args):
            pytest.fail('invalid target must be rejected locally')
    result = run_agent('查询记录编号-17', KnowledgeIndex(tmp_path / 'kb.sqlite3'), Forbidden(), allow_model_calls=True)
    assert result['rejection_code'] == 'positive_record_id_required'
    assert not result['model_used'] and result['plans'] == []


def test_final_numeric_contract_failure_can_repair_once_without_weakening_check(tmp_path):
    class Service:
        config = {'chat_model': 'fake'}
        chat_model = 'fake'
        embedding_model = ''
        def __init__(self):
            self.calls = 0
        def post(self, route, payload):
            self.calls += 1
            if self.calls == 1:
                return {'choices': [{'message': {'content': '', 'tool_calls': [{'id': 'one',
                    'function': {'name': 'kb_sources', 'arguments': '{}'}}]}}]}
            text = '知识库共有 999 份资料。' if self.calls == 2 else '知识库共有 0 份资料。'
            return {'choices': [{'message': {'content': json.dumps({'answer': text, 'claims': [
                {'text': text, 'citation_ids': ['kb-source-count']}]}, ensure_ascii=False)}}]}
    service = Service()
    result = run_agent('查看知识库', KnowledgeIndex(tmp_path / 'kb.sqlite3'), service, allow_model_calls=True)
    assert service.calls == 3 and result['answer_verified']
    assert '999' not in result['answer'] and '0' in result['answer']
