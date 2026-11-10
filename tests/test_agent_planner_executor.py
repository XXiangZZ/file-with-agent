import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from assistant.agent.executor import PlanExecutor
from assistant.agent.planner import PlanStore
from core.draft_manager import DraftManager
from core.record_manager import RecordManager
from core.template_manager import TemplateManager
from db import database


@pytest.fixture
def archive_context(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "archive.db")
    database.init_database()
    templates = TemplateManager()
    templates.init_database_templates()
    template_id = templates.get_template_id("文书")
    field_key = templates.get_fields("文书")[0]["key"]
    with database.get_cursor() as cursor:
        cursor.execute("INSERT INTO batches(name,template_id,template_name) VALUES(?,?,?)",
                       ("脱敏测试批次", template_id, "文书"))
        batch_id = cursor.lastrowid
    records = RecordManager()
    drafts = DraftManager()
    try:
        yield records, drafts, templates, batch_id, field_key
    finally:
        database.close_connection()


def _store(context):
    records, drafts, templates, batch_id, template_name = context
    return PlanStore(records, drafts, templates, batch_id, "文书")


def _counts():
    with database.get_cursor() as cursor:
        return tuple(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("records", "record_values", "drafts", "operation_log"))


def test_plan_creation_rejection_and_expiry_do_not_write(archive_context):
    store = _store((*archive_context[:4], archive_context[4]))
    baseline = _counts()
    plan = store.propose("create_record", {"name": "示例档案", "data": {archive_context[4]: "测试值"}})
    assert plan.status == "pending"
    assert _counts() == baseline
    store.decide(plan.plan_id, "rejected")
    assert _counts() == baseline


def test_create_record_and_log_commit_atomically(archive_context):
    records, drafts, templates, batch_id, field_key = archive_context
    store = PlanStore(records, drafts, templates, batch_id, "文书")
    plan = store.propose("create_record", {"name": "示例档案", "data": {field_key: "测试值"}})
    store.decide(plan.plan_id, "approved")
    result = PlanExecutor(records, drafts, templates).execute_plan(plan)
    assert result["status"] == "executed"
    record = records.get_record(result["result"]["record_id"])
    assert record["values"][field_key] == "测试值"
    with database.get_cursor() as cursor:
        logs = cursor.execute("SELECT operation_type,details FROM operation_log").fetchall()
    assert len(logs) == 1 and logs[0]["operation_type"] == "save_record"
    assert json.loads(logs[0]["details"])["agent_approved"] is True


def test_create_record_partial_failure_rolls_back_title_values_and_log(archive_context, monkeypatch):
    records, drafts, templates, batch_id, field_key = archive_context
    original = records.save_record_values

    def insert_then_fail(record_id, values, is_custom=False):
        original(record_id, values, is_custom)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(records, "save_record_values", insert_then_fail)
    store = PlanStore(records, drafts, templates, batch_id, "文书")
    plan = store.propose("create_record", {"name": "不会残留", "data": {field_key: "临时字段"}})
    store.decide(plan.plan_id, "approved")
    before = _counts()
    result = PlanExecutor(records, drafts, templates).execute_plan(plan)
    assert result["status"] == "failed"
    assert _counts() == before


def test_update_diff_and_field_fill_cannot_overwrite(archive_context):
    records, drafts, templates, batch_id, field_key = archive_context
    record_id = records.create_record(batch_id, templates.get_template_id("文书"),
        name="本地记录", template_name="文书", data={field_key: "已存在"})
    other_key = next(item["key"] for item in templates.get_fields("文书") if item["key"] != field_key)
    store = PlanStore(records, drafts, templates, batch_id, "文书")
    with pytest.raises(ValueError):
        store.propose("field_fill", {"record_id": record_id, "fields": {field_key: "覆盖值"}})
    plan = store.propose("update_record", {"record_id": record_id, "fields": {field_key: "新值"}})
    assert plan.preview["diff"][field_key] == {"old": "已存在", "new": "新值"}
    store.decide(plan.plan_id, "approved")
    outcome = PlanExecutor(records, drafts, templates).execute_plan(plan)
    assert outcome["status"] == "executed"
    assert records.get_record(record_id)["values"][field_key] == "新值"

    fill = store.propose("field_fill", {"record_id": record_id, "fields": {other_key: "填充值"}})
    store.decide(fill.plan_id, "approved")
    assert PlanExecutor(records, drafts, templates).execute_plan(fill)["status"] == "executed"
    assert records.get_record(record_id)["values"][other_key] == "填充值"


def test_executor_requires_approval_and_main_thread(archive_context):
    records, drafts, templates, batch_id, field_key = archive_context
    store = PlanStore(records, drafts, templates, batch_id, "文书")
    plan = store.propose("save_draft", {"draft_name": "样例草稿", "data": {field_key: "值"}})
    executor = PlanExecutor(records, drafts, templates)
    assert executor.execute_plan(plan)["code"] == "approval_required"
    store.decide(plan.plan_id, "approved")
    result = []
    thread = threading.Thread(target=lambda: result.append(executor.execute_plan(plan)))
    thread.start()
    thread.join()
    assert result[0]["code"] == "main_thread_required"
    assert _counts()[2:] == (0, 0)


def test_draft_and_review_plans_execute_after_confirmation(archive_context):
    records, drafts, templates, batch_id, field_key = archive_context
    store = PlanStore(records, drafts, templates, batch_id, "文书")
    draft = store.propose("save_draft", {"draft_name": "脱敏草稿", "data": {field_key: "草稿值"}})
    store.decide(draft.plan_id, "approved")
    assert PlanExecutor(records, drafts, templates).execute_plan(draft)["status"] == "executed"
    assert len(drafts.get_drafts_by_batch(batch_id)) == 1

    record_id = records.create_record(batch_id, templates.get_template_id("文书"),
        name="脱敏记录", template_name="文书", data={field_key: "现有值"})
    review = store.propose("mark_reviewed", {"record_id": record_id})
    store.decide(review.plan_id, "approved")
    assert PlanExecutor(records, drafts, templates).execute_plan(review)["status"] == "executed"
    assert records.get_record(record_id)["review_status"] == "reviewed"


def test_expired_approved_plan_writes_nothing(archive_context):
    records, drafts, templates, batch_id, field_key = archive_context
    store = PlanStore(records, drafts, templates, batch_id, "文书")
    plan = store.propose("save_draft", {"draft_name": "过期草稿", "data": {field_key: "不会写入"}})
    plan.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    store.decide(plan.plan_id, "approved")
    before = _counts()
    result = PlanExecutor(records, drafts, templates).execute_plan(plan)
    assert result["code"] == "plan_expired"
    assert plan.status == "rejected"
    assert _counts() == before
