import json
import sqlite3
from pathlib import Path
import sys
import numpy as np
import pytest
from assistant.index import KnowledgeIndex
from assistant.retrieval import ArchiveRetriever
from assistant.generation import ask


class Embeddings:
    model_name = 'synthetic#model'
    embedding_model = 'synthetic'
    def embed_documents(self, texts):
        return [[1., float('日期' in text), float('责任者' in text)] for text in texts]
    def embed_query(self, text):
        return [1., 0., 0.]


def make_index(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.sqlite3')
    for name, text, kind, scope in [('title', '题名：照录原文。', '规范', '文书'),
            ('date', '日期：原文日期。', '规范', '文书'),
            ('private', '题名：合同隐私。', '规范', '合同'),
            ('sample', '题名：非规范样例。', '样例', '文书')]:
        path = tmp_path / (name + '.txt')
        path.write_text(text, encoding='utf-8')
        index.import_file(path, kind, scope, embeddings=Embeddings())
    return index


def test_ann_scope_model_recall_sidecar_and_restart(tmp_path):
    index = make_index(tmp_path)
    before = index.path.read_bytes()
    result = index.ann_search('文书', ['规范'], [1., 0., 0.], Embeddings.model_name, 2)
    assert len(result) == 2 and '题名' in result[0].page_content
    assert all(doc.metadata['scope'] == '文书' and doc.metadata['kind'] == '规范' for doc in result)
    assert index.path.read_bytes() == before
    assert list(index.path.with_suffix('.sqlite3.ann').glob('*.npz'))
    restarted = KnowledgeIndex(index.path)
    assert [doc.metadata['id'] for doc in restarted.ann_search('文书', ['规范'], [1., 0., 0.], Embeddings.model_name, 2)] == [doc.metadata['id'] for doc in result]
    with pytest.raises(ValueError, match='模型'):
        index.ann_search('文书', None, [1., 0., 0.], 'other-model', 2)
    with pytest.raises(ValueError, match='维度'):
        index.ann_search('文书', None, [1., 0.], Embeddings.model_name, 2)
    with pytest.raises(ValueError, match='零向量'):
        index.ann_search('文书', None, [0., 0., 0.], Embeddings.model_name, 2)
    assert index.ann_search('不存在范围', None, [1., 0., 0.], Embeddings.model_name, 2) == []


def test_ann_refreshes_on_update_delete_and_detects_missing_vector(tmp_path):
    index = make_index(tmp_path)
    result = index.ann_search('文书', None, [1., 0., 0.], Embeddings.model_name, 2)
    original_id = result[0].metadata['id']
    # Includes changes made by a different KnowledgeIndex instance.
    other = KnowledgeIndex(index.path)
    title = tmp_path / 'title.txt'
    title.write_text('题名：已更新责任者。', encoding='utf-8')
    other.import_file(title, '规范', '文书', embeddings=Embeddings())
    fresh = index.ann_search('文书', None, [1., 0., 0.], Embeddings.model_name, 2)
    assert original_id not in {doc.metadata['id'] for doc in fresh}
    other.delete(title)
    assert list(index.path.with_suffix('.sqlite3.ann').glob('*.npz')) == []
    assert len(index.ann_search('文书', None, [1., 0., 0.], Embeddings.model_name, 2)) == 1
    with index.connect() as db:
        db.execute('DELETE FROM vectors')
    with pytest.raises(ValueError, match='缺少向量'):
        index.ann_search('文书', None, [1., 0., 0.], Embeddings.model_name, 2)


def test_ann_production_route_and_fallback_never_require_external_calls(tmp_path):
    index = make_index(tmp_path)
    docs = ArchiveRetriever(index=index, scope='文书', mode='ann', embeddings=Embeddings()).invoke('题名')
    assert docs and docs[0].metadata['retrieval_method'] == 'ann'
    assert all(doc.metadata['kind'] != '样例' for doc in docs)
    assert ask(index, '题名如何填写', '文书', mode='ann')['citations']
    class Failed(Embeddings):
        def embed_query(self, text):
            raise RuntimeError('offline')
    result = ask(index, '题名如何填写', '文书', mode='ann', embeddings=Failed())
    assert result['citations'] and '退回' in result['notice']


def test_corrupt_snapshot_rebuild_and_readonly_migration_guard(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'evaluation'))
    from ann_migrate import migrate
    index = make_index(tmp_path)
    report = migrate(index.path, '文书', Embeddings.model_name, kinds=['规范'])
    assert report['sqlite_unchanged'] and report['vectors'] == 2
    for path in index.path.with_suffix('.sqlite3.ann').glob('*.npz'):
        path.write_bytes(b'not a npz file')
    restarted = KnowledgeIndex(index.path)
    assert restarted.ann_search('文书', ['规范'], [1., 0., 0.], Embeddings.model_name, 2)
    business = tmp_path / 'archive.db'
    with sqlite3.connect(business) as db:
        db.execute('CREATE TABLE records(id INTEGER)')
    before = business.read_bytes()
    with pytest.raises(ValueError, match='业务库'):
        migrate(business, '文书', 'model')
    assert business.read_bytes() == before


def test_ann_model_mismatch_is_checked_before_optional_embedding_request(tmp_path):
    index = make_index(tmp_path)
    class NeverRequested(Embeddings):
        model_name = 'wrong-model'
        def embed_query(self, text):
            pytest.fail('stale model must be rejected before network')
    with pytest.raises(ValueError, match='模型'):
        ArchiveRetriever(index=index, mode='ann', scope='文书', embeddings=NeverRequested()).invoke('题名')


def test_ann_relative_neighbor_recall_in_fixed_low_dimensional_corpus(tmp_path):
    # Independent exact cosine reference, not comparing tree to itself.
    rng = np.random.default_rng(17)
    vectors = rng.normal(size=(400, 12))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    index = KnowledgeIndex(tmp_path / 'synthetic.sqlite3')
    path = tmp_path / 'source.txt'
    path.write_text('题名测试', encoding='utf-8')
    index.import_file(path, '规范', '文书', embeddings=Embeddings())
    with index.connect() as db:
        db.execute('DELETE FROM vectors')
        db.execute('DELETE FROM chunks')
        for i, vector in enumerate(vectors):
            meta = {'id': f'id-{i}', 'source': str(path.resolve()), 'page': i + 1, 'scope': '文书', 'kind': '规范'}
            db.execute('INSERT INTO chunks VALUES (?,?,?,?)', (meta['id'], meta['source'], '题名测试', json.dumps(meta)))
            db.execute('INSERT INTO vectors VALUES (?,?,?,?)', (meta['id'], json.dumps(vector.tolist()), Embeddings.model_name, 12))
    recalls = []
    for query in rng.normal(size=(8, 12)):
        exact = {f'id-{i}' for i in np.argsort(-(vectors @ (query / np.linalg.norm(query))))[:4]}
        result = index.ann_search('文书', None, query, Embeddings.model_name, 4, .15)
        recalls.append(len(exact & {doc.metadata['id'] for doc in result}) / 4)
    assert sum(recalls) / len(recalls) >= .9
