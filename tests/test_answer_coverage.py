import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from assistant.generation import verify_grounded_answer, verify_answer_coverage
from assistant.agent.model_adapter import ArchiveChatModel
from assistant.agent.runner import run_agent
from assistant.index import KnowledgeIndex


EVIDENCE = [{'id': 'rule', 'quote': '文件题名应照录原文标题，不得自行增补。', 'kind': '规范'}]
CLAIM = {'text': '文件题名应照录原文标题。', 'citation_ids': ['rule']}


@pytest.mark.parametrize('extra', [
    '系统已经保存了档案。', '文件题名无需照录原文标题。', '编号从1改为100。',
    '系统支持自动上传。', '，并已自动上传', '；保管期限为三十年',
])
def test_answer_extra_fact_is_hidden_in_every_public_answer_field(extra):
    result = verify_grounded_answer({'answer': CLAIM['text'] + extra, 'claims': [CLAIM]}, EVIDENCE)
    assert result['answer'] == CLAIM['text']
    assert not result['coverage']['input_fully_covered']
    assert result['coverage']['rewritten']


def test_safe_formatting_refusal_injection_and_paraphrase_are_conservative():
    result = verify_answer_coverage('1. 文件题名应照录原文标题；', [CLAIM])
    assert result['coverage']['input_fully_covered']
    result = verify_grounded_answer({'answer': '证据不足，但已自动保存正式档案。', 'claims': []}, [])
    assert '已自动保存' not in result['answer']
    assert result['coverage']['rewritten']
    result = verify_answer_coverage('按原标题填写题名。', [CLAIM])
    assert result['answer'] == CLAIM['text']  # no fuzzy or model-based paraphrase pass
    with pytest.raises(ValueError, match='未绑定引用'):
        verify_grounded_answer({'answer': '已经保存', 'claims': []}, [])


def test_negation_and_numeric_changes_do_not_pass_coverage():
    claims = [{'text': '日期不得猜测；记录编号为12。'}]
    for answer in ('日期可以猜测；记录编号为12。', '日期不得猜测；记录编号为120。'):
        result = verify_answer_coverage(answer, claims)
        assert not result['coverage']['input_fully_covered']
        assert result['answer'] == claims[0]['text']
    for original, changed in (('12.5元。', '99.5元。'), ('- 12元。', '12元。')):
        assert not verify_answer_coverage(changed, [{'text': original}])['coverage']['input_fully_covered']


def test_assistant_tool_calls_are_preserved_in_next_request():
    class Service:
        chat_model = 'fake'
        def post(self, route, payload):
            assistant = payload['messages'][1]
            assert assistant['tool_calls'][0]['id'] == 'call-1'
            assert json.loads(assistant['tool_calls'][0]['function']['arguments']) == {'record_id': 12}
            assert payload['messages'][2]['tool_call_id'] == 'call-1'
            return {'choices': [{'message': {'content': '证据不足'}}]}
    model = ArchiveChatModel(service=Service())
    model.invoke([HumanMessage(content='查询'), AIMessage(content='', tool_calls=[
        {'id': 'call-1', 'name': 'get_record_detail', 'args': {'record_id': 12}}]),
        ToolMessage(content='safe result', tool_call_id='call-1')])


def test_agent_never_returns_unverified_raw_answer(tmp_path):
    class Service:
        chat_model = 'fake'
        config = {'chat_model': 'fake'}
        def post(self, route, payload):
            return {'choices': [{'message': {'content': '已经上传全部档案'}}]}
    result = run_agent('查询', KnowledgeIndex(tmp_path / 'kb.sqlite3'), Service(), allow_model_calls=True)
    assert '已经上传' not in result['answer']
    assert result['answer'] == result['verified_answer']
    assert not result['answer_verified']
