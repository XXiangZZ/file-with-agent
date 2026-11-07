import json
from pathlib import Path
import pytest
from assistant.index import KnowledgeIndex
from assistant.manual import prepare_manual, ask_manual, SCOPE
from assistant.services import ModelService

GUIDES = Path(__file__).resolve().parents[1] / 'archive_tool/resources/manual'


@pytest.fixture
def index(tmp_path):
    index = KnowledgeIndex(tmp_path / 'manual.sqlite3')
    assert prepare_manual(index, GUIDES) == 7
    return index


@pytest.mark.parametrize('query, expected', [
    ('第一次用怎么开始？', '01_getting_started.md'),
    ('如何导入Excel？', '02_excel_import.md'),
    ('怎么导出当前批次？', '03_export.md'),
    ('怎么保存草稿？', '04_drafts.md'),
    ('日期格式错误如何校验？', '05_validation.md'),
    ('扫描件识别怎么用？', '06_ocr.md'),
    ('如何查找档案？', '07_search.md'),
])
def test_questions_cite_real_instructions(index, query, expected):
    result = ask_manual(index, query)
    assert expected in [Path(c['source']).name for c in result['citations']]
    assert not result['model_used']
    if expected == '02_excel_import.md':
        assert all(not c['source'].endswith('03_export.md') for c in result['citations'])
    for cite in result['citations']:
        assert cite['quote'] in Path(cite['source']).read_text(encoding='utf-8')
        assert cite['kind'] == '手册'


def test_out_of_scope_and_not_an_agent(index, tmp_path):
    path = tmp_path / 'wrong.md'
    path.write_text('# 软件自动联网同步\n1. 随意上传档案。', encoding='utf-8')
    index.import_file(path, kind='规范', scope=SCOPE)
    assert not ask_manual(index, '软件自动联网同步怎么用')['citations']
    result = ask_manual(index, '帮我立刻导出当前批次')
    assert result['citations']  # Explains export; no tools or mutations exist.
    assert '保存文件窗口' in str(result['citations'])
    with pytest.raises(ValueError, match='请输入'):
        ask_manual(index, '')


def test_bundled_guides_incremental_and_missing(index):
    before = index.sources()
    prepare_manual(index, GUIDES)
    assert index.sources() == before
    with pytest.raises(ValueError, match='资源缺失'):
        prepare_manual(index, GUIDES / 'missing')


def test_real_prompt_model_adapter_and_verified_steps(index, monkeypatch):
    service = ModelService({'base_url': 'http://localhost:11434/v1', 'chat_model': 'mock-only'})
    requests = []
    def fake_post(route, payload):
        requests.append((route, payload))
        assert payload['messages'][0]['role'] == 'system'
        assert '问题：如何导入Excel' in payload['messages'][1]['content']
        # Read the actual chain context instead of asserting a canned response.
        evidence = json.loads(payload['messages'][1]['content'].split('手册证据：', 1)[1])
        cite = next(c for c in evidence if c['source'].endswith('02_excel_import.md'))
        quote = next(line for line in cite['quote'].splitlines() if line.startswith('1.'))
        return {'choices': [{'message': {'content': json.dumps({'steps': [{'id': cite['id'], 'quote': quote}]})}}]}
    monkeypatch.setattr(service, 'post', fake_post)
    result = ask_manual(index, '如何导入Excel', service)
    assert requests and result['model_used']
    assert result['citations'][0]['quote'].startswith('1.')
    assert '模型' in result['mode']


@pytest.mark.parametrize('output', ['invalid json', '{"steps":[{"id":"invented","quote":"删除全部档案"}]}',
                                  '{"steps":[{"id":"a","quote":"1. 随意上传档案。"}]}'])
def test_model_failure_or_invented_quote_falls_back(index, monkeypatch, output):
    service = ModelService({'base_url': 'http://localhost:11434/v1', 'chat_model': 'mock-only'})
    monkeypatch.setattr(service, 'complete_prompt', lambda prompt: output)
    result = ask_manual(index, '如何导入Excel', service)
    assert '退回' in result['notice'] and not result['model_used']
    assert result['citations']


def test_model_timeout_and_embedding_failure(index, monkeypatch):
    service = ModelService({'base_url': 'http://localhost:11434/v1', 'chat_model': 'mock-only'})
    def unavailable(*args):
        raise RuntimeError('offline')
    monkeypatch.setattr(service, 'complete_prompt', unavailable)
    assert '退回' in ask_manual(index, '如何导入Excel', service)['notice']
    monkeypatch.setattr(service, 'embed_documents', unavailable)
    assert '退回' in ask_manual(index, '如何导入Excel', service, use_embeddings=True)['notice']
