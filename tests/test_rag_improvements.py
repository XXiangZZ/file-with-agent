"""Unseen local corpora test mechanics without fitting the 42-question labels."""
import math

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from assistant.generation import evidence_answer, ask
from assistant.manual import manual_evidence
from assistant.index import KnowledgeIndex
from assistant.retrieval import ArchiveRetriever, bm25_scores, reciprocal_rank_fusion


def doc(text, identity='a'):
    return Document(page_content=text, metadata={'id': identity, 'source': identity + '.txt',
        'page': 1, 'kind': '规范'})


def quotes(result):
    return [item['quote'] for item in result['citations']]


def test_generic_topic_does_not_drag_in_ocr_and_cross_page_conditions():
    documents = [doc('文件题名：照录标题，不能缩写。\n跨页题名：核对续页文字。\n文件题名：错字须核对扫描原件。')]
    focused = evidence_answer('文件题名如何填写', documents)
    assert quotes(focused) == ['文件题名：照录标题，不能缩写。']
    assert len(quotes(evidence_answer('文件题名如何填写', documents, selection='legacy'))) == 3
    for item in focused['citations']:
        assert item['quote'] in documents[0].page_content
    assert '错字' in ''.join(quotes(evidence_answer('文件题名出现错字如何处理', documents)))
    assert '续页' in ''.join(quotes(evidence_answer('跨页题名如何处理', documents)))


def test_multi_field_missing_condition_is_attached_only_to_its_field():
    documents = [doc('题名：疑似错字需核对扫描原件。\n日期：缺失时不得推算。')]
    assert len(quotes(evidence_answer('题名错字与日期缺失如何处理', documents))) == 2
    documents = [doc('题名：无题名时转人工补录。\n日期：缺失时不得推算。')]
    assert len(quotes(evidence_answer('题名缺失和日期缺失如何处理', documents))) == 2
    assert len(quotes(evidence_answer('题名缺失和日期缺失如何处理', documents, selection='legacy'))) == 1
    # A different topic order must also work; no fixture question IDs are used.
    assert len(quotes(evidence_answer('日期缺失和题名缺失如何处理', documents))) == 2


def test_conflicting_evidence_is_not_silently_hidden_or_adjudicated():
    documents = [doc('条款一保管期限：五年。', 'one'),
                 doc('条款二保管期限：二十五年。', 'two'),
                 doc('保管期限效力：没有生效文件不能判定优先条款。', 'three')]
    result = evidence_answer('保管期限条款冲突如何处理', documents)
    assert len(result['citations']) == 3
    assert '不据此推断' in result['answer']
    assert quotes(evidence_answer('保管期限哪个条款优先', documents)) == [documents[2].page_content]


def test_unknown_topic_stays_abstained_no_ocr_fuzzy_rewrite():
    documents = [doc('责任者：按发文单位填写。')]
    assert not evidence_answer('责仼者如何填写', documents)['citations']
    assert not evidence_answer('密级如何填写', documents)['citations']
    assert not evidence_answer('文件题名如何填写', [])['citations']
    with pytest.raises(ValueError):
        evidence_answer('题名', documents, selection='made-up')


def test_manual_action_blocks_excel_shared_heading_but_preserves_prerequisites():
    documents = [doc('# Excel导入\n1. 先选择批次。\n2. 点击导入。', 'in'),
                 doc('# Excel导出\n1. 选择目录导出。', 'out')]
    evidence, _ = manual_evidence('Excel导入怎么做', documents)
    assert [item['id'] for item in evidence] == ['in']
    assert '先选择批次' in evidence[0]['quote']
    assert len(manual_evidence('Excel导入怎么做', documents, selection='legacy')[0]) == 2
    assert len(manual_evidence('Excel导入后导出', documents)[0]) == 2


def test_bm25_idf_tf_saturation_length_normalization_and_empty_query():
    docs = [doc('rare common'), doc('common'), doc('common')]
    # Unigrams (ASCII words) make this independently calculable without bigrams.
    scores = bm25_scores('rare', docs)
    idf = math.log1p((3 - 1 + .5) / (1 + .5))
    # expanded tokens for the first document: rare, common, rarecommon -> length 3.
    average = 5 / 3
    expected = idf * 2.2 / (1 + 1.2 * (.25 + .75 * 3 / average))
    assert scores[0] == pytest.approx(expected)
    assert scores[1:] == [0, 0]
    assert scores[0] > bm25_scores('common', docs)[0]
    repeated = [doc('rare ' * 20), doc('rare')]
    score = bm25_scores('rare', repeated, b=0)
    assert 1 < score[0] / score[1] < 2.2  # TF gains saturate, not 20-fold.
    length_docs = [doc('rare'), doc('rare ' + 'filler ' * 30)]
    assert bm25_scores('rare', length_docs)[0] > bm25_scores('rare', length_docs)[1]
    assert bm25_scores('', docs) == [0, 0, 0]
    assert bm25_scores('unseen', docs) == [0, 0, 0]
    assert bm25_scores('题名', [doc('')]) == [0]
    assert bm25_scores('题名', []) == []
    for params in ({'k1': 0}, {'k1': float('nan')}, {'b': 2}):
        with pytest.raises(ValueError):
            bm25_scores('rare', docs, **params)


def test_rrf_uses_ranks_not_incommensurate_raw_scores_and_ignores_duplicates():
    scores = reciprocal_rank_fusion([['a', 'b'], ['b', 'a']], rank_constant=60)
    assert scores['a'] == scores['b'] == pytest.approx(1 / 61 + 1 / 62)
    assert reciprocal_rank_fusion([['a', 'a', 'b']]) == reciprocal_rank_fusion([['a', 'b']])
    assert reciprocal_rank_fusion([[], []]) == {}
    for invalid in (0, -1, True, 1.2):
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([['a']], rank_constant=invalid)


def test_bm25_rrf_scoping_parameters_ties_vector_validation_and_rollback(tmp_path, monkeypatch):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    for name, scope in (('a', '文书'), ('b', '文书'), ('contract', '合同')):
        path = tmp_path / (name + '.txt')
        path.write_text('文件题名：照录原文。', encoding='utf-8')
        index.import_file(path, '规范', scope)
    result = ArchiveRetriever(index=index, scope='文书', mode='bm25_rrf').invoke('文件题名')
    assert len(result) == 2
    assert [d.metadata['id'] for d in result] == sorted(d.metadata['id'] for d in result)
    assert all(d.metadata['bm25_rank'] and d.metadata['semantic_rank'] and
               d.metadata['retrieval_method'] == 'bm25_rrf' for d in result)
    assert ArchiveRetriever(index=index, scope='空范围', mode='bm25_rrf').invoke('题名') == []
    assert ArchiveRetriever(index=index, mode='bm25_rrf').invoke('') == []
    for params in ({'bm25_k1': 0}, {'bm25_b': 1.01}, {'rrf_k': 0}, {'rrf_k': True}):
        with pytest.raises(ValidationError):
            ArchiveRetriever(index=index, **params)
    monkeypatch.setenv('ARCHIVE_RAG_RETRIEVAL', 'bm25_rrf')
    assert ArchiveRetriever(index=index).mode == 'bm25_rrf'
    monkeypatch.setenv('ARCHIVE_RAG_RETRIEVAL', 'hybrid')
    monkeypatch.setenv('ARCHIVE_RAG_EVIDENCE', 'legacy')
    assert ArchiveRetriever(index=index).mode == 'hybrid'
    assert ask(index, '文件题名', '文书')['citations']

    class FakeEmbeddings:
        model_name = 'fake-not-real-service'
        def embed_documents(self, texts):
            return [[1., 0.] for _ in texts]
        def embed_query(self, text):
            return [1., 0., 0.]
    fake = FakeEmbeddings()
    for name in ('a', 'b'):
        index.import_file(tmp_path / (name + '.txt'), '规范', '文书', embeddings=fake)
    with pytest.raises(ValueError, match='维度不一致'):
        ArchiveRetriever(index=index, mode='bm25_rrf', scope='文书', embeddings=fake).invoke('题名')
    fake.embed_query = lambda text: [1., 0.]
    assert ArchiveRetriever(index=index, mode='bm25_rrf', scope='文书', embeddings=fake).invoke('题名')
    fake.model_name = 'another-model'
    with pytest.raises(ValueError, match='嵌入模型已变更'):
        ArchiveRetriever(index=index, mode='bm25_rrf', scope='文书', embeddings=fake).invoke('题名')
