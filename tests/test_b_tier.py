import json

import pytest

from assistant.index import KnowledgeIndex
from assistant.retrieval import ArchiveRetriever, route_intent, rewrite_query


class FakeEmbeddings:
    def __init__(self, model_name):
        self.model_name = model_name
        self.document_calls = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


def test_query_rewrite_routes_and_retriever_marks_rerank_metadata(tmp_path):
    assert '题名' in rewrite_query('标题怎么填写')
    assert route_intent('标题怎么填写') == 'field'
    assert route_intent('如何导出当前批次') == 'manual'

    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    rules = tmp_path / 'rules.txt'
    manual = tmp_path / 'manual.txt'
    rules.write_text('文件题名：按原文著录。', encoding='utf-8')
    manual.write_text('# 批次导出\n1. 点击导出并选择批次。', encoding='utf-8')
    index.import_file(rules, kind='规范', scope='文书')
    index.import_file(manual, kind='手册', scope='文书')

    docs = ArchiveRetriever(index=index, scope='文书', k=2).invoke('如何导出当前批次')
    assert docs and docs[0].metadata['kind'] == '手册'
    assert docs[0].metadata['intent'] == 'manual'
    assert docs[0].metadata['rerank_score'] >= docs[0].metadata['retrieval_score'] * .5


def test_embedding_model_change_requires_reembedding_and_rebuild(tmp_path):
    path = tmp_path / 'rule.txt'
    path.write_text('文件题名：按原文著录。', encoding='utf-8')
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    first = FakeEmbeddings('endpoint-a#model-a')
    second = FakeEmbeddings('endpoint-b#model-b')
    index.import_file(path, scope='文书', embeddings=first)

    with pytest.raises(ValueError, match='嵌入模型已变更'):
        ArchiveRetriever(index=index, scope='文书', embeddings=second).invoke('文件题名')

    assert '更新向量' in index.import_file(path, scope='文书', embeddings=second)
    assert second.document_calls == 1
    rows = index.vector_rows('文书', expected_model=second.model_name)
    assert rows and all(vector is not None for _, vector in rows)

    third = FakeEmbeddings('endpoint-c#model-c')
    assert '已索引' in index.rebuild(embeddings=third)
    assert all(vector is not None for _, vector in index.vector_rows(
        '文书', expected_model=third.model_name))
    assert '已索引' in index.rebuild()
    assert all(vector is not None for _, vector in index.vector_rows(
        '文书', expected_model=third.model_name))


def test_failed_reembedding_preserves_existing_vectors(tmp_path):
    path = tmp_path / 'rule.txt'
    path.write_text('文件题名：按原文著录。', encoding='utf-8')
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    working = FakeEmbeddings('stable-model')
    index.import_file(path, scope='文书', embeddings=working)

    failed = FakeEmbeddings('broken-model')
    failed.embed_documents = lambda texts: (_ for _ in ()).throw(RuntimeError('offline'))
    with pytest.raises(RuntimeError):
        index.import_file(path, scope='文书', embeddings=failed)
    rows = index.vector_rows('文书', expected_model='stable-model')
    assert rows and all(vector is not None for _, vector in rows)


def test_feedback_persists_ratings_corrections_and_failures(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    index.record_feedback('如何导出？', '选择批次。', [{'quote': '选择批次。'}],
                          scope='文书', helpful=False, correction='需先选择批次')
    index.record_feedback('日期怎么填？', scope='文书', failure='TimeoutError')
    all_rows = index.feedback_samples()
    review = index.feedback_samples(needs_review=True)
    assert all_rows[0]['helpful'] is False
    assert all_rows[0]['correction'] == '需先选择批次'
    assert len(review) == 2
    assert review[1]['failure'] == 'TimeoutError'


def test_feedback_regression_replays_saved_negative_sample(tmp_path, capsys):
    from evaluation.feedback_regression import run

    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    source = tmp_path / 'rule.txt'
    source.write_text('文件题名：按原文著录。', encoding='utf-8')
    index.import_file(source, scope='文书')
    index.record_feedback('文件题名如何填写', '旧回答', scope='文书',
                          helpful=False, correction='只按原文著录')
    run(index.path)
    report = json.loads(capsys.readouterr().out)
    assert report['sample_count'] == 1
    assert report['corrections_requiring_human_review'] == 1
    assert report['rows'][0]['correction'] == '只按原文著录'
