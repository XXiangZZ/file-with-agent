import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evaluation'))
import semantic_eval
import scale_eval


def test_judge_schema_rejects_missing_duplicate_invented_quotes_and_truthy_strings():
    sample = {'question': '日期', 'contexts': ['日期缺失不得猜测。'], 'claims': ['日期可以猜测。']}
    valid = {'faithfulness': [{'index': 0, 'verdict': False, 'reason': '否定冲突', 'evidence': '日期缺失不得猜测。'}],
             'relevance': [{'index': 0, 'verdict': True, 'reason': '回答日期规则', 'evidence': '日期缺失不得猜测。'}]}
    assert semantic_eval.validate(json.dumps(valid, ensure_ascii=False), sample)
    for bad in (
        {**valid, 'faithfulness': []},
        {**valid, 'relevance': valid['relevance'] * 2},
        {**valid, 'relevance': [{**valid['relevance'][0], 'evidence': '伪造出处'}]},
        {**valid, 'relevance': [{**valid['relevance'][0], 'verdict': 'true'}]},
    ):
        with pytest.raises(ValueError):
            semantic_eval.validate(json.dumps(bad, ensure_ascii=False), sample)


def test_context_precision_and_empty_claim_denominators():
    rows = [{'judgement': {'faithfulness': [], 'relevance': [
        {'index': 0, 'verdict': False}, {'index': 1, 'verdict': True}]}}, {'judgement': None}]
    measured = semantic_eval.aggregate(rows)
    assert measured['faithfulness'] is None
    assert measured['context_precision'] == .5
    assert measured['context_average_precision'] == .5
    assert measured['failed_samples'] == 1


def test_offline_semantic_preparation_never_reads_model_config(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('offline means no config or service')
    monkeypatch.setattr(semantic_eval, 'ModelService', forbidden)
    monkeypatch.setattr(semantic_eval, 'load_config', forbidden)
    report = semantic_eval.run(tmp_path, limit=3)
    assert report['status'] == 'not_run_offline'
    assert not report['real_judge_used'] and report['calibration_label_agreement'] is None
    assert (tmp_path / 'review_samples.json').is_file()
    with pytest.raises(ValueError):
        semantic_eval.run(tmp_path, config_path='config')


def test_same_model_cannot_be_called_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic_eval, 'load_config', lambda _: {'chat_model': 'same-model'})
    with pytest.raises(ValueError, match='不同'):
        semantic_eval.run(tmp_path, config_path='gen', judge_config='judge', allow_model_calls=True)


def test_benchmark_executes_real_temporary_index_queries():
    result = scale_eval.benchmark(20, dimensions=4, repeats=2)
    assert result['chunks'] == 20 and result['selected_scope_chunks'] == 2
    assert result['exact_hybrid_retrieval']['repeats'] == 2
    assert result['python_peak_tracemalloc_bytes'] > 0
