"""Regression for metric meaning, corpus labels and the offline authorization gate."""
import importlib.util
import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p0_eval', ROOT / 'evaluation/p0_eval.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_metric_denominators_do_not_reward_empty_or_irrelevant_citations():
    question = {'id': 'case', 'category': 'multi_hop', 'task': 'policy', 'scope': '文书',
                'question': '文件题名如何填写',
                'gold': [['a.txt', 1, '照录标题'], ['b.txt', 2, '核对副题名']]}
    doc = Document(page_content='文件题名：照录标题。\n文件日期：格式YYYYMMDD。',
                   metadata={'id': 'one', 'source': 'a.txt', 'page': 1})
    corpus = {('a.txt', 1): doc.page_content}
    result = {'answer': '摘录', 'citations': [
        {**doc.metadata, 'quote': '文件题名：照录标题。'},
        {**doc.metadata, 'quote': '文件日期：格式YYYYMMDD。'}]}
    row = evaluation.score_answer(question, [doc], result, corpus)
    measured = evaluation.metrics([row])
    assert measured['recall@1'] == .5
    assert measured['citation_authenticity'] == 1
    assert measured['citation_correctness'] == .5
    assert measured['all_gold_covered_rate'] == 0
    assert measured['unsupported_refusal_rate'] is None
    assert measured['generated_claim_support_rate'] is None

    refusal = dict(question, id='unsupported', gold=[])
    row = evaluation.score_answer(refusal, [], {'answer': '证据不足', 'citations': []}, corpus)
    measured = evaluation.metrics([row])
    assert measured['unsupported_refusal_rate'] == 1
    assert measured['recall@1'] is None
    assert measured['citation_correctness'] is None
    assert measured['extractive_fact_support_pass_rate'] is None
    forged = {'answer': '错误引用', 'citations': [{**doc.metadata, 'quote': '从未存在的句子'}]}
    row = evaluation.score_answer(question, [doc], forged, corpus)
    assert row['citation_authentic_count'] == row['citation_correct_count'] == row['support_passed'] == 0


def test_full_offline_report_is_repeatable_and_never_creates_service(tmp_path, monkeypatch):
    import assistant.services as services
    def forbidden(*args, **kwargs):
        raise AssertionError('default evaluation must never construct a model service or use network')
    monkeypatch.setattr(services, 'ModelService', forbidden)
    monkeypatch.setattr(services, 'urlopen', forbidden)
    first = evaluation.run(output_dir=tmp_path / 'one')
    second = evaluation.run(output_dir=tmp_path / 'two')
    assert 30 <= first['question_count'] <= 50
    assert first['metrics'] == second['metrics']
    assert first['rows'] == second['rows']
    assert first['dataset_sha256'] == second['dataset_sha256']
    assert first['external_embeddings']['status'] == 'not_run_no_authorization'
    assert set(first['categories']) == {'normal', 'paraphrase', 'ocr_typo', 'multi_hop', 'conflict', 'refusal'}
    assert len(first['rows']) == len(evaluation.METHODS) * first['question_count']
    assert (tmp_path / 'one/p0_comparison.md').exists()
    assert json.loads((tmp_path / 'one/p0_results.json').read_text(encoding='utf-8'))['metrics'] == first['metrics']
    # The old four methods must still reproduce the accepted P0 baseline.
    baseline = json.loads((ROOT / 'evaluation/p0_baseline.json').read_text(encoding='utf-8'))
    assert first['dataset_sha256'] == baseline['dataset_sha256']
    for method, old_metrics in baseline['metrics'].items():
        assert first['metrics'][method] == old_metrics
    before, after = first['metrics']['hybrid'], first['metrics']['hybrid_filtered']
    assert after['recall@3'] == before['recall@3']
    assert after['citation_correctness'] > before['citation_correctness']
    assert after['all_gold_covered_rate'] > before['all_gold_covered_rate']
    assert after['false_refusal_rate'] <= before['false_refusal_rate']
    assert set(first['changes']['hybrid_filtered']['coverage_improved']) == {'M03', 'M04'}
    assert first['changes']['hybrid_filtered']['remaining_incomplete'] == ['O04']
    # An experimental regression must remain visible, not removed from reports.
    assert 'M03' in first['changes']['bm25_rrf']['recall3_regressed']
    with pytest.raises(ValueError, match='allow-model-calls'):
        evaluation.run(output_dir=tmp_path, config_path='never-read.json')
    with pytest.raises(ValueError, match='config'):
        evaluation.run(output_dir=tmp_path, allow_model_calls=True)


def test_invalid_labels_fail_before_any_network_call(tmp_path, monkeypatch):
    import assistant.services as services
    class NeverRequested:
        embedding_model = 'fake'
        def __init__(self, config):
            pass
        def embed_documents(self, texts):
            raise AssertionError('bad labels must fail before embedding')
    monkeypatch.setattr(services, 'ModelService', NeverRequested)
    config = tmp_path / 'config.json'
    config.write_text('{"embedding_model":"fake"}', encoding='utf-8')
    question = {'id': 'bad', 'category': 'normal', 'task': 'policy', 'scope': '文书',
                'question': '题名如何填写', 'gold': [['missing.txt', 1, '不存在的期望']]}
    dataset = tmp_path / 'questions.json'
    dataset.write_text(json.dumps([question], ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='期望证据不存在'):
        evaluation.run(dataset, tmp_path / 'output', allow_model_calls=True, config_path=config)


def test_optional_embeddings_path_uses_only_explicit_fake_service(tmp_path, monkeypatch):
    import assistant.services as services
    class FakeEmbeddings:
        embedding_model = 'fake-embedding-not-real-model-evidence'
        model_name = 'fake#embedding'
        calls = 0
        def __init__(self, config):
            pass
        def embed_documents(self, texts):
            type(self).calls += 1
            return [[1., float('题名' in text), float('日期' in text)] for text in texts]
        def embed_query(self, text):
            return self.embed_documents([text])[0]
    monkeypatch.setattr(services, 'ModelService', FakeEmbeddings)
    config = tmp_path / 'config.json'
    config.write_text('{"embedding_model":"fake"}', encoding='utf-8')
    report = evaluation.run(output_dir=tmp_path / 'report', allow_model_calls=True, config_path=config)
    assert report['external_embeddings']['status'] == 'run'
    assert report['external_embeddings']['model'] == FakeEmbeddings.embedding_model
    assert 'external_embeddings' in report['metrics']
    assert FakeEmbeddings.calls > 0
