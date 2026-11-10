import json

from assistant.agent.tools import build_tools
from assistant.index import KnowledgeIndex
from core.record_manager import RecordManager
from core.template_manager import TemplateManager
from core.draft_manager import DraftManager
from db import database


def test_read_tools_keep_archive_values_local_and_policy_keeps_citations(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "archive.db")
    database.init_database()
    templates = TemplateManager()
    templates.init_database_templates()
    template_id = templates.get_template_id("文书")
    field_key = templates.get_fields("文书")[0]["key"]
    with database.get_cursor() as cursor:
        cursor.execute("INSERT INTO batches(name,template_id,template_name) VALUES(?,?,?)",
                       ("脱敏批次", template_id, "文书"))
        batch_id = cursor.lastrowid
    records = RecordManager()
    records.create_record(batch_id, template_id, name="机密档案名称", template_name="文书",
                          data={field_key: "机密字段值"})
    index = KnowledgeIndex(tmp_path / "knowledge.sqlite3")
    rules = tmp_path / "rules.txt"
    rules.write_text("文件题名：照录原文标题，不得自行增补。", encoding="utf-8")
    index.import_file(rules, kind="规范", scope="文书")
    tools, _ = build_tools(index, record_manager=records, draft_manager=DraftManager(),
        template_manager=templates, batch_id=batch_id, template_name="文书")
    by_name = {item.name: item for item in tools}

    policy = json.loads(by_name["ask_policy"].invoke({"question": "文件题名如何填写？", "scope": "文书"}))
    assert policy["citations"]
    assert "source" in policy["citations"][0] and "page" in policy["citations"][0]

    result = by_name["search_records"].invoke({"keyword": "机密字段值"})
    assert "机密字段值" not in result and "机密档案名称" not in result
    payload = json.loads(result)
    assert payload["records"][0]["id"] == 1
    assert payload["citations"] and payload["citations"][0]["page"] is None
    database.close_connection()


def test_write_tool_returns_only_pending_summary_without_writes(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "archive.db")
    database.init_database()
    templates = TemplateManager()
    templates.init_database_templates()
    template_id = templates.get_template_id("文书")
    field_key = templates.get_fields("文书")[0]["key"]
    with database.get_cursor() as cursor:
        cursor.execute("INSERT INTO batches(name,template_id,template_name) VALUES(?,?,?)",
                       ("脱敏批次", template_id, "文书"))
        batch_id = cursor.lastrowid
    index = KnowledgeIndex(tmp_path / "knowledge.sqlite3")
    tools, plans = build_tools(index, record_manager=RecordManager(),
        draft_manager=DraftManager(), template_manager=templates,
        batch_id=batch_id, template_name="文书", allow_model_calls=True)
    proposal = next(item for item in tools if item.name == "propose_create_record")
    before = _counts()
    raw = proposal.invoke({"name": "本地档案名", "batch_id": batch_id,
        "template_name": "文书", "data": {field_key: "私有字段内容"}})
    preview = json.loads(raw)
    assert preview["status"] == "pending"
    assert "私有字段内容" not in raw and "本地档案名" not in raw
    assert len(plans.get_pending()) == 1
    assert _counts() == before
    database.close_connection()


def _counts():
    with database.get_cursor() as cursor:
        return tuple(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("records", "record_values", "drafts", "operation_log"))
