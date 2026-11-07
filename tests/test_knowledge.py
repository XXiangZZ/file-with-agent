import pytest
from assistant.index import KnowledgeIndex
from assistant.parsing import Parser


def test_incremental_atomic_delete_rebuild(tmp_path):
    path = tmp_path / 'rule.txt'
    path.write_text('题名：按原文著录。\f日期：按落款著录。', encoding='utf-8')
    index = KnowledgeIndex(tmp_path / 'kb.db')
    assert '2 页' in index.import_file(path)
    assert '跳过' in index.import_file(path)
    docs = index.documents('通用')
    assert {d.metadata['page'] for d in docs} == {1, 2}
    assert all('imported' in d.metadata and 'start_index' in d.metadata for d in docs)
    path.write_text('', encoding='utf-8')
    with pytest.raises(ValueError):
        index.import_file(path)
    assert len(index.documents('通用')) == 2
    path.write_text('题名：保留副题名。', encoding='utf-8')
    index.import_file(path)
    assert len(index.documents('通用')) == 1
    with index.connect() as db:
        db.execute("UPDATE sources SET version='old'")
    with pytest.raises(ValueError, match='失效'):
        index.documents('通用')
    assert '已索引' in index.rebuild()
    index.delete(str(path.resolve()))
    assert not index.documents('通用')


def test_pdf_pages_and_ocr_adapter(tmp_path):
    import fitz
    from PIL import Image
    pdf = tmp_path / 'two.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((50, 50), 'Title: First page')
        doc.new_page()
        doc.save(pdf)
    class FakeOCR:
        def recognize_full_image(self, image):
            return [{'text': '扫描原文', 'score': .9}]
    parser = Parser(FakeOCR())
    docs = parser.parse(pdf)
    assert len(docs) == 2 and docs[1].metadata['ocr']
    assert docs[1].page_content == '扫描原文'
    image = tmp_path / 'scan.png'
    Image.new('RGB', (50, 50), 'white').save(image)
    assert parser.parse(image)[0].metadata['page'] == 1


def test_scope_and_samples_are_not_rules(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.db')
    for name, kind, scope in [('a', '规范', '合同'), ('b', '样例', '文书'), ('c', '规范', '文书')]:
        path = tmp_path / f'{name}.txt'
        path.write_text('日期：不详时留空', encoding='utf-8')
        index.import_file(path, kind, scope)
    assert len(index.documents('文书')) == 1
