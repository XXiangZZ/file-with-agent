"""Explicit real-service acceptance on sanitized fixtures, never archive data.

Retrieval: full 42-question corpus via the existing P0 evaluator. Generation:
fixed 14-question subset with raw and displayed verification metrics separated.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archive_tool'))
from langsmith import tracing_context
from assistant.generation import (GROUNDING_CHAT_PROMPT, GROUNDING_PROMPT, citation,
                                  verify_grounded_answer, verify_answer_coverage)
from assistant.index import KnowledgeIndex
from assistant.manual import PROMPT, local_answer, verify_model_answer
from assistant.services import ModelService, load_config
import p0_eval

GENERATION_IDS = ('N01', 'N02', 'N03', 'P01', 'M01', 'M03', 'M04', 'C05', 'R01', 'R08',
                  'N05', 'N06', 'P05', 'R05')


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def generation_metrics(rows):
    claims = sum(row['raw_claim_count'] for row in rows)
    passed = sum(row['supported_claim_count'] for row in rows)
    checked = sum(row.get('checked_claim_count', 0) for row in rows)
    policy = [row for row in rows if row['task'] == 'policy' and row['parsed']]
    coverage_checked = [row for row in policy if row.get('coverage_checked')]
    unsupported = [row for row in rows if not row['answerable']]
    attempted = [row for row in rows if not row.get('model_skipped_no_evidence')]
    return {'questions': len(rows), 'model_attempted_questions': len(attempted),
        'model_skipped_no_evidence': len(rows) - len(attempted),
        'parse_rate': ratio(sum(row['parsed'] for row in attempted), len(attempted)),
        'raw_claim_count': claims, 'supported_claim_count': passed,
        'checked_claim_count': checked, 'unassessed_claim_count': claims - checked,
        'generated_claim_support_rate': ratio(passed, claims),
        'assessed_claim_support_rate': ratio(passed, checked),
        'raw_answer_coverage_rate': ratio(sum(row['raw_answer_covered'] for row in coverage_checked), len(coverage_checked)),
        'raw_answer_coverage_checked': len(coverage_checked),
        'raw_answer_coverage_unassessed': len(policy) - len(coverage_checked),
        'output_verified_rate': ratio(sum(row['output_verified'] for row in rows), len(rows)),
        'abstention_rate_on_unsupported': ratio(sum(row['abstained'] for row in unsupported), len(unsupported)),
        'coverage_rewrite_count': sum(row['coverage_rewritten'] for row in rows),
        'failure_count': sum(bool(row['error_type']) for row in rows),
        'manual_step_support_rate': ratio(sum(row['supported_step_count'] for row in rows),
                                          sum(row['raw_step_count'] for row in rows))}


def evaluate_generation(question, docs, service):
    started = perf_counter()
    row = {'id': question['id'], 'task': question['task'], 'answerable': bool(question['gold']),
           'parsed': False, 'raw_claim_count': 0, 'supported_claim_count': 0, 'checked_claim_count': 0,
           'raw_step_count': 0, 'supported_step_count': 0,
           'raw_answer_covered': False, 'coverage_rewritten': False,
           'coverage_checked': False,
           'output_verified': False, 'abstained': False, 'error_type': None}
    try:
        if question['task'] == 'policy':
            evidence = [citation(doc) for doc in docs]
            prompt = GROUNDING_CHAT_PROMPT.format_prompt(instructions=GROUNDING_PROMPT,
                question=question['question'], evidence=json.dumps(evidence, ensure_ascii=False))
            raw = service.complete_prompt(prompt)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict) or not isinstance(parsed.get('claims'), list):
                raise ValueError('invalid_claim_schema')
            row['parsed'] = True
            row['raw_claim_count'] = len(parsed['claims'])
            # Separate answer->claims text coverage from claim->source support.
            # This audit alone does not authorize displaying unverified claims.
            if isinstance(parsed.get('answer'), str) and all(isinstance(claim, dict) and
                    isinstance(claim.get('text'), str) for claim in parsed['claims']):
                coverage = verify_answer_coverage(parsed['answer'], parsed['claims'])['coverage']
                row['coverage_checked'] = True
                row['raw_answer_covered'] = coverage['input_fully_covered']
            by_id = {item['id']: item for item in evidence}
            all_support = True
            for claim in parsed['claims']:
                try:
                    # Count rejected claims as failures, rather than dropping them.
                    verify_grounded_answer({'answer': claim['text'], 'claims': [claim]}, evidence)
                    sources = [by_id[identity]['quote'] for identity in claim['citation_ids']]
                    support = service.check_claim_support(claim['text'], sources)
                except (ValueError, TypeError, KeyError):
                    support = False
                row['checked_claim_count'] += 1
                row['supported_claim_count'] += int(support)
                all_support = all_support and support
            verified = verify_grounded_answer(parsed, evidence)
            row['coverage_rewritten'] = verified['coverage']['rewritten']
            row['output_verified'] = all_support
            row['abstained'] = not verified['claims']
            # Do not persist the raw answer or prompts. Only display already
            # checked synthetic claims if both local and model checks pass.
            row['displayed_answer'] = verified['answer'] if all_support else '证据不足，模型事实句未通过支持核验。'
            if not all_support:
                row['error_type'] = 'claim_support_failed'
        else:
            result = local_answer(question['question'], docs, selection='legacy')
            if not result['citations']:
                row.update(parsed=True, output_verified=True, abstained=True,
                           displayed_answer=result['answer'], model_skipped_no_evidence=True)
                return row
            prompt = PROMPT.format_prompt(question=question['question'],
                evidence=json.dumps(result['citations'], ensure_ascii=False))
            raw = service.complete_prompt(prompt)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict) or not isinstance(parsed.get('steps'), list):
                raise ValueError('invalid_step_schema')
            row['parsed'] = True
            row['raw_step_count'] = len(parsed['steps'])
            for step in parsed['steps']:
                try:
                    verify_model_answer(json.dumps({'steps': [step]}, ensure_ascii=False), result)
                    row['supported_step_count'] += 1
                except (ValueError, TypeError):
                    pass
            verified = verify_model_answer(raw, result)
            row.update(output_verified=True, abstained=not verified['citations'],
                       displayed_answer=verified['answer'])
    except Exception as exc:
        row['error_type'] = type(exc).__name__
        row['displayed_answer'] = '证据不足，本题服务或核验失败。'
    finally:
        row['elapsed_ms'] = round((perf_counter() - started) * 1000, 2)
    return row


def refresh_saved_report(path):
    """Recalculate summaries only; older interrupted checks stay unassessed."""
    path = Path(path)
    report = json.loads(path.read_text(encoding='utf-8'))
    for row in report['rows']:
        # Pre-audit reports only reached coverage on successful whole validation
        # or a later entailment failure; service failures cannot imply mismatch.
        row.setdefault('coverage_checked', row['task'] == 'policy' and row['parsed'] and
                       (row['output_verified'] or row['error_type'] == 'claim_support_failed'))
        row.setdefault('checked_claim_count', row['raw_claim_count'] if row['error_type'] != 'RuntimeError'
                       else row['supported_claim_count'])
    report['generation_metrics'] = generation_metrics(report['rows'])
    report['metrics_recomputed_from_saved_observations'] = True
    report['limits'] = [note for note in report['limits'] if not note.startswith('整段覆盖率以成功解析')]
    for note in (
        '事实支持率为确认通过占全部原始claim的保守比例；检查中断的claim单列未评估，不当作已证明错误。',
        'raw_answer_coverage_rate只对实际完成覆盖检查的答案计算；服务中断而未检查的答案单列，不当作文本不匹配。',
    ):
        if note not in report['limits']:
            report['limits'].append(note)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def write_summary(output_dir):
    """Local-only regeneration from reports; never reads model configuration."""
    output_dir = Path(output_dir)
    generation = json.loads((output_dir / 'real_p0_results.json').read_text(encoding='utf-8'))
    agent = json.loads((output_dir / 'agent_real_results.json').read_text(encoding='utf-8'))
    scripted = json.loads((output_dir / 'agent_results.json').read_text(encoding='utf-8'))
    g, a, s = generation['generation_metrics'], agent['metrics'], scripted['metrics']
    r = generation['retrieval_metrics_42_questions']
    def fmt(value):
        return 'N/A' if value is None else f'{value:.3f}'
    lines = ['# P0 覆盖校验与真实服务首轮验收', '',
        '本次改动和首轮验收已完成；真实模型能力没有全项达标。数据为开发者合成小样本，非生产效果。', '',
        f"模型：聊天 `{generation['chat_model']}`；嵌入 `{generation['embedding_model']}`。",
        f"规模：42题检索；{generation['completed_generation_cases']}/{generation['planned_generation_cases']}题生成；"
        f"{agent['completed_cases']}/{agent['planned_cases']}题真实Agent；{scripted['completed_cases']}题脚本Agent。", '',
        '| 检查项 | 首轮结果 | 分母/解释 |', '|---|---:|---|',
        f"| 外部嵌入 Recall@1 / @3 | {fmt(r['recall@1'])} / {fmt(r['recall@3'])} | 34道可回答题，按相关页宏平均 |",
        f"| 外部嵌入 + 旧摘录：引用对齐 | {fmt(r['citation_correctness'])} | 对应real_retrieval中的external_embeddings组，不混用新过滤收益 |",
        f"| 原始生成claim确认支持 | {g['supported_claim_count']}/{g['raw_claim_count']}={fmt(g['generated_claim_support_rate'])} | 以全部原始claim为分母，含未评估项 |",
        f"| 已完成检查的claim支持 | {g['supported_claim_count']}/{g['checked_claim_count']}={fmt(g['assessed_claim_support_rate'])} | 未评估{g['unassessed_claim_count']}条，另列 |",
        f"| 原始answer覆盖 | {fmt(g['raw_answer_coverage_rate'])} | 实际检查{g['raw_answer_coverage_checked']}题，未评估{g['raw_answer_coverage_unassessed']}题 |",
        f"| 生成验收通过 | {fmt(g['output_verified_rate'])} | {g['questions']}题，包含本地跳过模型的手册拒答；失败{g['failure_count']}题 |",
        f"| 真实Agent选工具达标 | {fmt(a['tool_selection_rate'])} | {a['cases']}题，严格集合匹配 |",
        f"| 真实Agent关键参数匹配 | {fmt(a['parameter_match_rate'])} | 与标注关键参数子集比较 |",
        f"| 真实Agent工具契约达标 | {fmt(a['tool_contract_success_rate'])} | 不等同于最终问答成功 |",
        f"| 真实Agent只读问答端到端 | {fmt(a['end_to_end_answer_success_rate'])} | {sum(row['kind']=='read' for row in agent['rows'])}道只读题，需工具契约及有核验事实句 |",
        f"| 真实计划重新校验 | {fmt(a['plan_validation_rate'])} | {sum(row['plan_count'] for row in agent['rows'])}个待确认计划，不批准不执行 |",
        f"| 审批前业务零写入 | {fmt(a['preapproval_zero_write_rate'])} | 比较临时库记录、字段、草稿和日志完整快照 |",
        f"| 脚本计划模拟审批执行 | {fmt(s['simulated_plan_execution_rate'])} | {s['simulated_execution_count']}类计划，仅临时库 |", '',
        '保留的失败与边界：', '',
        f"- 生成失败/未完成项：{[(row['id'], row['error_type']) for row in generation['rows'] if row['error_type']]}；无自动重试或挑选最好结果。",
        f"- 真实Agent未达端到端契约：{[row['id'] for row in agent['rows'] if not row['task_success']]}；严格集合口径也可能把额外合理前置查询计作不符。",
        '- A13/A14及非法任务的安全阻断或隐藏率不等同于模型主动拒绝率。模型把非法ID改成合法但错误ID，也会参数匹配失败。',
        '- 脚本Agent的知识库列表题虽调用正确，但工具没有可引用事实证据，未计为完整问答成功；脚本控制通过不能冒充模型能力。',
        '- claim支持仍用既有token门槛与同一聊天模型的蕴含检查，不是独立裁判；整段answer校验只是关闭answer绕过claims的出口。', '',
        '新增功能与简练实现：', '',
        '- 整段答案覆盖：generation.verify_answer_coverage按规范化分句精确匹配；有未覆盖文本时只展示已经核验的claims。无claim的拒答统一为本地安全文本。',
        '- Agent输出出口：runner返回的answer与verified_answer均为安全文本，不再在answer中返回原始未核验回答。',
        '- 多轮工具消息：model_adapter保留AIMessage.tool_calls并与后续ToolMessage关联。',
        '- Agent题集与验收：20题脚本控制回归、17题真实模型选工具/参数/计划/拒绝验收；每题独立临时库。',
        '- 真实服务验收：复用urllib适配器及现有配置，显式授权才调用；原始失败和未评估分母均保留。', '',
        '复现、源代码映射、测试与未覆盖风险见p0_acceptance_readme.md。默认评测不联网；真实验收需要网络，但仅发送脱敏夹具。',
        '本次未修改审批执行器/数据库schema/业务UI/EXE；未增加import/export/restore、UI动作、计划持久化或自动重试等P1功能。', '']
    (output_dir / 'p0_acceptance.md').write_text('\n'.join(lines), encoding='utf-8')


def run(output_dir=None, *, config_path=None, allow_model_calls=False):
    if not allow_model_calls or config_path is None:
        raise ValueError('必须同时提供--allow-model-calls与--config，不发送默认请求')
    config = load_config(config_path)
    if not config.get('chat_model') or not config.get('embedding_model'):
        raise ValueError('必须配置聊天与嵌入模型')
    output_dir = Path(output_dir or ROOT / 'evaluation')
    output_dir.mkdir(parents=True, exist_ok=True)
    # Reuse the full fixed 42-question retrieval comparison, separate output folder.
    retrieval = p0_eval.run(output_dir=output_dir / 'real_retrieval',
        allow_model_calls=True, config_path=config_path)
    service = ModelService(config)
    questions = p0_eval.load_questions(ROOT / 'evaluation/p0_questions.json')
    selected = [question for question in questions if question['id'] in GENERATION_IDS]
    rows = []
    with tempfile.TemporaryDirectory(prefix='archive-real-generation-') as temp:
        index = KnowledgeIndex(Path(temp) / 'knowledge.sqlite3')
        corpus, _ = p0_eval.prepare(index)
        p0_eval.validate_gold(selected, corpus)
        p0_eval.prepare(index, service)
        for question in selected:
            with tracing_context(enabled=False):
                try:
                    docs = p0_eval.retrieve(index, question, 'external_embeddings', service)
                    row = evaluate_generation(question, docs, service)
                except Exception as exc:
                    row = {
                        'id': question['id'], 'task': question['task'], 'answerable': bool(question['gold']),
                        'parsed': False, 'raw_claim_count': 0, 'supported_claim_count': 0,
                        'raw_step_count': 0, 'supported_step_count': 0, 'raw_answer_covered': False,
                        'coverage_rewritten': False, 'output_verified': False, 'abstained': False,
                        'error_type': type(exc).__name__}
            rows.append(row)
            report = {'real_models_used': True, 'chat_model': service.chat_model,
                'embedding_model': service.embedding_model, 'planned_generation_cases': len(selected),
                'completed_generation_cases': len(rows),
                'retrieval_metrics_42_questions': retrieval['metrics']['external_embeddings'],
                'generation_metrics': generation_metrics(rows), 'rows': rows,
                'limits': ['42题检索与固定14题生成子集，开发者合成，非生产效果、非独立盲测。',
                    '生成事实支持率以原始claims为分母，计入被拒绝的claim；使用本地token检查与同一聊天模型蕴含判断，不是独立事实裁判。',
                    '整段覆盖率以成功解析的规范答案为分母；失败/空样本另报，不用过滤后100%掩盖原始失败。',
                    '手册原文不足时跳过模型并本地拒答；不把此算作模型生成能力。',
                    '只使用合成规范和内置指南；未读取生产档案或草稿。真实调用需要网络，离线指临时本地数据验收，不是断网运行。']}
            (output_dir / 'real_p0_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'id': row['id'], 'verified': row['output_verified'],
                              'error': row['error_type']}, ensure_ascii=False), flush=True)
    print(json.dumps(report['generation_metrics'], ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--allow-model-calls', action='store_true')
    parser.add_argument('--summary-only', action='store_true', help='仅从现有JSON生成汇总，不读取配置、不联网')
    args = parser.parse_args()
    if args.summary_only:
        write_summary(args.output_dir or ROOT / 'evaluation')
    else:
        run(args.output_dir, config_path=args.config, allow_model_calls=args.allow_model_calls)
