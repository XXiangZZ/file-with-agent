from langchain_core.documents import Document
from assistant.index import KnowledgeIndex
from assistant.generation import ask, suggest
from assistant.retrieval import ArchiveRetriever
from assistant.services import ModelService
import pytest


def test_chain_retrieval_scope_no_answer(tmp_path):
    index = KnowledgeIndex(tmp_path / 'kb.db')
    for name, text, scope in [('rules', '文件题名：应照录原文标题，不能自行增补。', '文书'),
                              ('other', '文件题名：合同应写买卖双方名称。', '合同')]:
        path = tmp_path / f'{name}.txt'
        path.write_text(text, encoding='utf-8')
        index.import_file(path, scope=scope)
    answer = ask(index, '标题怎么填写', '文书')
    assert answer['citations']
    assert all('合同' not in c['quote'] for c in answer['citations'])
    assert not ask(index, '密级如何填写', '文书')['citations']
    assert ArchiveRetriever(index=index, scope='文书', mode='keyword').invoke('题名')


def test_suggestions_abstain_ambiguity_and_invalid_dates():
    fields = [{'name': n, 'key': str(i)} for i, n in enumerate(['文件题名', '文件日期', '责任者'])]
    doc = Document(page_content='题名：关于培训的通知\n日期：2026年11月07日\n责任者：示例办公室',
                   metadata={'source': 'anonymous.txt', 'page': 2})
    result = suggest([doc], fields)
    assert [r['value'] for r in result] == ['关于培训的通知', '20261107', '示例办公室']
    assert all(r['citation']['quote'] in doc.page_content for r in result)
    invalid = Document(page_content='日期：2026年13月40日\n题名：另一份通知', metadata=doc.metadata)
    assert suggest([invalid], fields)[1]['value'] is None
    assert suggest([doc, invalid], fields)[0]['value'] is None
    ocr = Document(page_content='日其：2O26年11月07日', metadata={**doc.metadata, 'ocr': True})
    assert suggest([ocr], fields)[1]['value'] is None
    assert not suggest([doc], [{'key': 'received', 'name': '接收日期'},
                               {'key': 'filed', 'name': '归档日期'},
                               {'key': 'volume', 'name': '案卷题名'}])
    empty = Document(page_content='题名：\n日期：20261107', metadata=doc.metadata)
    assert suggest([empty], fields)[0]['value'] is None


def test_model_selection_verifies_quote_and_unknown_id(monkeypatch):
    service = ModelService({'base_url': 'http://localhost:11434/v1', 'chat_model': 'test'})
    result = {'answer': '', 'citations': [{'id': 'a', 'quote': '文件题名照录原文', 'source': 'a', 'page': 1}]}
    monkeypatch.setattr(service, 'post', lambda *args: {'choices': [{'message': {'content':
        '{"quotes":[{"id":"a","quote":"自行编造题名"},{"id":"other","quote":"文件题名"}]}'}}]})
    assert not service.select_evidence('题名', result)['citations']
    with pytest.raises(ValueError):
        ModelService({'base_url': 'http://example.com/v1'})
