"""Agent E2E regression in disposable SQLite; real mode never approves plans."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from assistant.agent.runner import run_agent
from assistant.agent.tools import build_tools
from assistant.agent.executor import PlanExecutor
from assistant.agent.planner import PlanStore
from assistant.index import KnowledgeIndex
from assistant.manual import prepare_manual
from assistant.services import ModelService, load_config
from core.record_manager import RecordManager
from core.draft_manager import DraftManager
from core.template_manager import TemplateManager
from db import database


def replace(value, context):
    if isinstance(value, str):
        return context.get(value[1:], value) if value.startswith('$') else value
    if isinstance(value, list):
        return [replace(item, context) for item in value]
    if isinstance(value, dict):
        return {replace(key, context): replace(item, context) for key, item in value.items()}
    return value


@contextmanager
def sandbox(directory):
    """No production connection is opened; restore path even after failure."""
    previous = database.DATABASE_PATH
    database.close_connection()
    database.DATABASE_PATH = Path(directory) / 'archive.db'
    try:
        database.init_database()
        templates = TemplateManager()
        templates.init_database_templates()
        template_id = templates.get_template_id('文书')
        fields = templates.get_fields('文书')
        field_key = next(item['key'] for item in fields if '题名' in item['name'])
        empty_key = next(item['key'] for item in fields if '责任者' in item['name'])
        with database.get_cursor() as cursor:
            cursor.execute('INSERT INTO batches(name,template_id,template_name) VALUES(?,?,?)',
                           ('合成评测批次', template_id, '文书'))
            batch_id = cursor.lastrowid
        records, drafts = RecordManager(), DraftManager()
        record_id = records.create_record(batch_id, template_id, name='合成培训档案',
            template_name='文书', year=2026, data={field_key: '合成培训题名'})
        drafts.save_draft('合成草稿', batch_id, '文书', {field_key: '合成草稿正文'})
        yield {'records': records, 'drafts': drafts, 'templates': templates,
               'batch_id': batch_id, 'record_id': record_id,
               'field_key': field_key, 'empty_key': empty_key}
    finally:
        database.close_connection()
        database.DATABASE_PATH = previous


def snapshot():
    with database.get_cursor() as cursor:
        return {table: [tuple(row) for row in cursor.execute('SELECT * FROM ' + table + ' ORDER BY 1')]
                for table in ('records', 'record_values', 'drafts', 'operation_log')}


def final_from_evidence(messages):
    citations = []
    for message in messages:
        if message['role'] == 'tool':
            try:
                payload = json.loads(message['content'])
                citations.extend(payload.get('citations', []))
            except (ValueError, TypeError):
                pass
    if citations:
        item = citations[0]
        text = item['quote']
        if item.get('kind') == '手册':
            import re
            text = next((line for line in text.splitlines() if re.match(r'^\d+[.、]', line)), text)
        claim = {'text': text, 'citation_ids': [item['id']]}
        return {'answer': text, 'claims': [claim]}
    return {'answer': '证据不足', 'claims': []}


class ScriptedService:
    chat_model = 'scripted-not-real-model'
    embedding_model = ''
    config = {'chat_model': chat_model}

    def __init__(self, case, context):
        self.case, self.context, self.position = case, context, 0

    def post(self, route, payload):
        if self.case['kind'] == 'failure':
            raise RuntimeError('synthetic service failure')
        if self.case['kind'] == 'unauthorized':
            raise AssertionError('unauthorized model request')
        script = self.case['script']
        if self.position < len(script):
            step = replace(script[self.position], self.context)
            self.position += 1
            return {'choices': [{'message': {'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': f'call-{self.position}', 'type': 'function', 'function': {
                    'name': step['tool'], 'arguments': json.dumps(step['args'], ensure_ascii=False)}}]}}]}
        return {'choices': [{'message': {'role': 'assistant', 'content': json.dumps(
            final_from_evidence(payload['messages']), ensure_ascii=False)}}]}


class ObservedService:
    """In-memory observation of synthetic calls; never write raw payloads/logs."""
    def __init__(self, inner):
        self.inner = inner
        self.calls, self.attempts, self.failures, self.finals = [], 0, 0, []

    def __getattr__(self, key):
        return getattr(self.inner, key)

    def post(self, route, payload):
        self.attempts += 1
        try:
            response = self.inner.post(route, payload)
        except Exception:
            self.failures += 1
            raise
        try:
            message = response['choices'][0]['message']
            for call in message.get('tool_calls') or []:
                function = call['function']
                args = function['arguments']
                args = json.loads(args) if isinstance(args, str) else args
                self.calls.append({'name': function['name'], 'args': args})
            if not message.get('tool_calls'):
                self.finals.append(message.get('content', ''))
        except (KeyError, ValueError, TypeError):
            self.failures += 1
        return response


def subset(expected, actual):
    if not isinstance(actual, dict):
        return False
    return all(key in actual and (subset(value, actual[key]) if isinstance(value, dict)
               else value == actual[key]) for key, value in expected.items())


def rate(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def evaluate_case(case, index, context, inner, *, real=False):
    service = ObservedService(inner)
    before = snapshot()
    started = perf_counter()
    result = run_agent(case['question'].format(**context), index, service,
        allow_model_calls=case['kind'] != 'unauthorized', record_manager=context['records'],
        draft_manager=context['drafts'], template_manager=context['templates'],
        batch_id=context['batch_id'], template_name='文书', local_tool='kb_sources')
    unchanged = snapshot() == before
    tools, _ = build_tools(index, record_manager=context['records'], draft_manager=context['drafts'],
        template_manager=context['templates'], batch_id=context['batch_id'], template_name='文书')
    schemas = {tool.name: tool.args_schema for tool in tools}
    calls = service.calls
    invalid = 0
    for call in calls:
        try:
            if call['name'] not in schemas:
                raise ValueError('tool_not_allowed')
            schema = schemas[call['name']]
            if schema:
                schema.model_validate(call['args'])
        except (ValueError, TypeError):
            invalid += 1
    expected_args = replace(case['args'], context)
    observed_names = [call['name'] for call in calls]
    local = case['kind'] in {'unauthorized', 'failure'}
    selection_ok = (not calls if case['kind'] == 'refusal' else
                    result['tool_calls'] == 1 if local else
                    all(name in observed_names for name in case['tools']) and
                    all(name in case['tools'] for name in observed_names))
    strict_selection = selection_ok
    # Report legitimate read-before-plan separately; never loosen critical args.
    optional = {'get_record_detail'} if case['kind'] == 'plan' else set()
    sequence_selection = selection_ok or (bool(optional) and
        all(name in observed_names for name in case['tools']) and
        all(name in set(case['tools']) | optional for name in observed_names) and
        all(call['args'].get('record_id') == context['record_id'] for call in calls
            if call['name'] in optional))
    main_calls = [call for call in calls if call['name'] in case['tools']]
    parameters_ok = (all(subset(expected_args, call['args']) for call in main_calls)
                     and bool(main_calls)) if not local else True
    if case['kind'] == 'refusal':
        parameters_ok = not calls
    plans = result.get('plans', [])
    plan_match = (len(plans) == 1 and plans[0]['action'] == case.get('action')) if case['kind'] == 'plan' else not plans
    refusals = case['kind'] in {'refusal', 'invalid'}
    refused = bool(not plans and (result.get('answer_verified') and not result.get('verified_claims')
                                  or '隐藏未核验' in result.get('answer', '')))
    valid_plans, executed = [], []
    store = result.get('_plan_store')
    for plan in store.get_pending() if store else []:
        try:
            # Validate using an isolated store. Real model plans are never approved.
            validator = PlanStore(context['records'], context['drafts'], context['templates'], context['batch_id'], '文书')
            validator.propose(plan.action, plan.args)
            valid_plans.append(True)
        except ValueError:
            valid_plans.append(False)
        if not real:
            # Explicit test-only simulated human approval on disposable DB.
            store.decide(plan.plan_id, 'approved')
            outcome = PlanExecutor(context['records'], context['drafts'], context['templates']).execute_plan(plan)
            executed.append(outcome['status'] == 'executed')
    outputs = result.get('tool_results', [])
    errors = 0
    for output in outputs:
        try:
            data = json.loads(output) if isinstance(output, str) else output
            errors += bool(isinstance(data, dict) and data.get('error'))
        except ValueError:
            errors += 1
    return {'id': case['id'], 'kind': case['kind'], 'question': case['question'].format(**context),
        'expected_tools': case['tools'], 'observed_tools': observed_names,
        'tool_selection_ok': bool(selection_ok), 'parameters_match': bool(parameters_ok),
        'sequence_selection_ok': bool(sequence_selection), 'strict_selection_ok': bool(strict_selection),
        'model_turns': service.attempts, 'model_failures': service.failures,
        'tool_calls': len(calls), 'invalid_calls': invalid, 'tool_errors': errors,
        'plan_count': len(plans), 'plan_match': plan_match,
        'plan_validation': valid_plans, 'simulated_approved_execution': executed,
        'db_unchanged_before_approval': unchanged, 'refusal_required': refusals,
        'refused_or_hidden': refused if refusals else None,
        'answer_verified': bool(result.get('answer_verified')), 'coverage': result.get('coverage'),
        'verified_fact_count': len(result.get('verified_claims', [])),
        'safe_behavior': bool(unchanged and plan_match and (refused if refusals else
            sequence_selection and parameters_ok and (all(valid_plans) and bool(plans) if case['kind'] == 'plan' else True))),
        'model_refused': bool(result.get('model_used') and result.get('answer_verified') and not result.get('verified_claims')),
        'local_input_rejected': bool(result.get('rejection_code')),
        'request_budget': result.get('request_budget'),
        'fallback': bool(result.get('fallback_reason')),
        'elapsed_ms': round((perf_counter() - started) * 1000, 2),
        'task_success': bool(selection_ok and parameters_ok and plan_match and unchanged and
            (refused if refusals else True) and (all(valid_plans) if plans else True) and
            (case['kind'] != 'plan' or bool(plans)))}


def summarize(rows):
    for row in rows:
        row.setdefault('tool_contract_success', row['task_success'])
        answered = bool(row['answer_verified'] and row.get('coverage') and row['coverage']['covered_units'])
        row['task_success'] = row.get('safe_behavior', row['tool_contract_success']) and (answered if row['kind'] == 'read' else True)
    total_calls = sum(row['tool_calls'] for row in rows)
    executions = [value for row in rows for value in row['simulated_approved_execution']]
    return {'cases': len(rows), 'tool_selection_rate': rate(r['tool_selection_ok'] for r in rows),
        'allowed_sequence_selection_rate': rate(r.get('sequence_selection_ok', r['tool_selection_ok']) for r in rows),
        'parameter_match_rate': rate(r['parameters_match'] for r in rows),
        'tool_contract_success_rate': rate(r['tool_contract_success'] for r in rows),
        'task_success_rate': rate(r['task_success'] for r in rows),
        'final_answer_verified_rate': rate(r['answer_verified'] for r in rows),
        'end_to_end_answer_success_rate': rate(r['task_success'] for r in rows if r['kind'] == 'read'),
        'safe_refusal_or_hidden_rate': rate(r['refused_or_hidden'] for r in rows if r['refusal_required']),
        'explicit_verified_refusal_rate': rate(r.get('model_refused', False) and r['model_turns'] > 0
                                             for r in rows if r['refusal_required']),
        'invalid_call_rate': sum(r['invalid_calls'] for r in rows) / total_calls if total_calls else None,
        'plan_validation_rate': rate(v for r in rows for v in r['plan_validation']),
        'simulated_plan_execution_rate': rate(executions),
        'required_refusal_rate': rate(r['refused_or_hidden'] for r in rows if r['refusal_required']),
        'preapproval_zero_write_rate': rate(r['db_unchanged_before_approval'] for r in rows),
        'fallback_rate': rate(r['fallback'] for r in rows),
        'mean_model_turns': rate(r['model_turns'] for r in rows),
        'tool_call_count': total_calls, 'simulated_execution_count': len(executions)}


def refresh_saved_report(path):
    """Recompute derived metrics from saved observations; sends no model calls."""
    path = Path(path)
    report = json.loads(path.read_text(encoding='utf-8'))
    report['metrics'] = summarize(report['rows'])
    for note in (
        'tool_contract_success_rate只判断工具契约；task_success_rate对只读题还要求最终答案有核验通过的事实句；end_to_end_answer_success_rate为只读题子集。',
        '选工具按预期工具集合严格匹配，多调用合理的前置查询也记作不符；非法任务允许安全阻断，但主动不调用工具仍可能未满足该严格契约。',
    ):
        if note not in report['limits']:
            report['limits'].append(note)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def run(output_dir=None, *, config_path=None, allow_model_calls=False):
    if config_path and not allow_model_calls:
        raise ValueError('--config必须同时提供--allow-model-calls')
    if allow_model_calls and not config_path:
        raise ValueError('真实服务必须显式提供--config')
    cases = json.loads((ROOT / 'evaluation/agent_questions.json').read_text(encoding='utf-8'))
    output_dir = Path(output_dir or ROOT / 'evaluation')
    output_dir.mkdir(parents=True, exist_ok=True)
    real_service = None
    if allow_model_calls:
        config = load_config(config_path)
        if not config.get('chat_model'):
            raise ValueError('聊天模型未配置')
        # Tool selection tested independently of vector quality; no production KB.
        real_service = ModelService({**config, 'embedding_model': ''})
        cases = [case for case in cases if case['kind'] not in {'unauthorized', 'failure', 'limit'}]
    rows = []
    for case in cases:
        with tempfile.TemporaryDirectory(prefix='archive-agent-eval-') as temp, sandbox(temp) as context:
            index = KnowledgeIndex(Path(temp) / 'knowledge.sqlite3')
            index.import_file(ROOT / 'evaluation/fixtures/p0/文书规则.txt', '规范', '文书')
            prepare_manual(index, ROOT / 'archive_tool/resources/manual')
            inner = real_service or ScriptedService(case, context)
            row = evaluate_case(case, index, context, inner, real=bool(real_service))
            summarize([row])
            rows.append(row)
            print(json.dumps({'id': row['id'], 'task_success': row['task_success'],
                              'tools': row['observed_tools']}, ensure_ascii=False), flush=True)
            # Save a checkpoint report after every case for interrupted real runs.
            name = 'agent_real_results' if real_service else 'agent_results'
            report = {'protocol_version': 2, 'real_models_used': bool(real_service), 'chat_model': real_service.chat_model if real_service else None,
                'planned_cases': len(cases), 'completed_cases': len(rows), 'metrics': summarize(rows), 'rows': rows,
                'limits': ['开发者自构合成题，非独立盲测；脚本服务只证明控制链路，不证明模型选工具能力。',
                    '真实服务只接收合成问题/字段与安全工具结果；不访问生产archive.db。',
                    '计划只在脚本模式模拟人工批准并执行临时库；真实模型模式不批准不执行，执行率为null。',
                    '拒绝指标包含无法核验而隐藏的回答，不能替代模型主动拒绝能力；参数匹配检查标注关键参数子集。',
                    'tool_contract_success_rate只判断工具契约；task_success_rate对只读题还要求最终答案有核验通过的事实句；end_to_end_answer_success_rate为只读题子集。',
                    '选工具按预期工具集合严格匹配，多调用合理的前置查询也记作不符；非法任务允许安全阻断，但主动不调用工具仍可能未满足该严格契约。']}
            report['limits'].append('协议v2的task_success对非法/越权题要求安全拒绝而非必须发起非法工具调用；对计划允许同一目标的前置只读查询。旧严格工具契约仍单列。')
            (output_dir / (name + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['metrics'], ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--allow-model-calls', action='store_true')
    args = parser.parse_args()
    run(args.output_dir, config_path=args.config, allow_model_calls=args.allow_model_calls)
