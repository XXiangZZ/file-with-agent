"""Acceptance machinery is tested offline; no vendor service in pytest."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evaluation'))
import agent_eval
import real_p0_eval
from assistant.generation import citation
from langchain_core.documents import Document
from db import database


def test_agent_full_scripted_control_path_does_not_construct_real_service(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('no real service in default evaluation')
    monkeypatch.setattr(agent_eval, 'ModelService', forbidden)
    original = database.DATABASE_PATH
    result = agent_eval.run(tmp_path)
    assert database.DATABASE_PATH == original
    assert result['completed_cases'] == 20
    assert not result['real_models_used']
    assert result['metrics']['preapproval_zero_write_rate'] == 1
    assert result['metrics']['plan_validation_rate'] == 1
    assert result['metrics']['simulated_plan_execution_rate'] == 1
    assert result['metrics']['simulated_execution_count'] == 5
    assert result['metrics']['required_refusal_rate'] == 1
    assert next(row for row in result['rows'] if row['id'] == 'A18')['model_turns'] == 0
    assert next(row for row in result['rows'] if row['id'] == 'A20')['model_turns'] == 4
    assert next(row for row in result['rows'] if row['id'] == 'A19')['fallback']
    # The invalid ID intentionally reaches Pydantic; must remain in denominator.
    assert result['metrics']['invalid_call_rate'] > 0
    with pytest.raises(ValueError):
        agent_eval.run(tmp_path, config_path='must-not-read.json')


def test_sandbox_restores_database_path_after_failure(tmp_path):
    original = database.DATABASE_PATH
    with pytest.raises(RuntimeError):
        with agent_eval.sandbox(tmp_path):
            assert Path(database.DATABASE_PATH).parent == tmp_path
            raise RuntimeError('injected')
    assert database.DATABASE_PATH == original
    assert getattr(database._local, 'conn', None) is None


def test_real_mode_cannot_be_triggered_by_config_alone(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('no config/service access without authorization')
    monkeypatch.setattr(real_p0_eval, 'load_config', forbidden)
    with pytest.raises(ValueError, match='allow-model-calls'):
        real_p0_eval.run(tmp_path, config_path='never-read')
    with pytest.raises(ValueError, match='config'):
        agent_eval.run(tmp_path, allow_model_calls=True)
    assert real_p0_eval.generation_metrics([])['generated_claim_support_rate'] is None


def test_raw_claim_failures_and_extra_answer_sentences_are_counted():
    doc = Document(page_content='文件题名应照录原文，不得自行增补。',
                   metadata={'id': 'a', 'source': 'synthetic.txt', 'page': 1})
    class Fake:
        def complete_prompt(self, prompt):
            return json.dumps({'answer': '文件题名应照录原文。系统支持自动上传。', 'claims': [
                {'text': '文件题名应照录原文。', 'citation_ids': ['a']},
                {'text': '系统自动上传档案。', 'citation_ids': ['a']} ]}, ensure_ascii=False)
        def check_claim_support(self, claim, evidence):
            return '上传' not in claim
    question = {'id': 'synthetic', 'task': 'policy', 'gold': [['synthetic.txt', 1, '照录原文']],
                'question': '题名如何填写'}
    row = real_p0_eval.evaluate_generation(question, [doc], Fake())
    assert row['raw_claim_count'] == 2
    assert row['supported_claim_count'] == 1
    assert not row['output_verified']
    assert real_p0_eval.generation_metrics([row])['generated_claim_support_rate'] == .5


def test_uncovered_answer_rewritten_after_successful_claim_support():
    doc = Document(page_content='文件题名应照录原文，不得自行增补。',
                   metadata={'id': 'a', 'source': 'synthetic.txt', 'page': 1})
    class Fake:
        def complete_prompt(self, prompt):
            return json.dumps({'answer': '文件题名应照录原文。系统支持自动上传。', 'claims': [
                {'text': '文件题名应照录原文。', 'citation_ids': ['a']} ]}, ensure_ascii=False)
        def check_claim_support(self, claim, evidence):
            return True
    question = {'id': 'synthetic', 'task': 'policy', 'gold': [['synthetic.txt', 1, '照录原文']],
                'question': '题名如何填写'}
    row = real_p0_eval.evaluate_generation(question, [doc], Fake())
    assert row['output_verified'] and row['coverage_rewritten']
    assert not row['raw_answer_covered']
    assert '上传' not in row['displayed_answer']


def test_real_agent_plans_are_validated_but_never_approved(tmp_path):
    cases = json.loads((ROOT / 'evaluation/agent_questions.json').read_text(encoding='utf-8'))
    case = next(case for case in cases if case['id'] == 'A08')
    with agent_eval.sandbox(tmp_path) as context:
        from assistant.index import KnowledgeIndex
        before = agent_eval.snapshot()
        row = agent_eval.evaluate_case(case, KnowledgeIndex(tmp_path / 'kb.sqlite3'), context,
                                      agent_eval.ScriptedService(case, context), real=True)
        assert row['plan_count'] == 1 and row['plan_validation'] == [True]
        assert row['simulated_approved_execution'] == []
        assert agent_eval.snapshot() == before
