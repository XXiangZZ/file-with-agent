"""Main-thread-only executor for explicitly approved plans."""
import threading
from datetime import datetime, timezone

from core.logger import Logger
from db.database import atomic_transaction
from .planner import PlanStore


class PlanExecutor:
    def __init__(self, record_manager, draft_manager, template_manager, logger=None):
        self.record_manager = record_manager
        self.draft_manager = draft_manager
        self.template_manager = template_manager
        self.logger = logger or Logger()

    def execute_plan(self, plan):
        if threading.current_thread() is not threading.main_thread():
            return {"status": "failed", "code": "main_thread_required",
                    "message": "批准计划只能在主线程执行"}
        if plan.status != "approved":
            return {"status": "failed", "code": "approval_required",
                    "message": "计划尚未获得本地用户确认"}
        if datetime.fromisoformat(plan.expires_at) <= datetime.now(timezone.utc):
            plan.status = "rejected"
            return {"status": "failed", "code": "plan_expired", "message": "计划已过期"}
        try:
            with atomic_transaction():
                result = self._execute(plan)
                self.logger.log(self._log_type(plan.action), self._log_details(plan, result))
            plan.status = "executed"
            return {"status": "executed", "plan_id": plan.plan_id, "result": result}
        except Exception as exc:
            plan.status = "failed"
            return {"status": "failed", "plan_id": plan.plan_id,
                    "code": type(exc).__name__, "message": "执行失败，已回滚本计划全部数据库写入"}

    def _execute(self, plan):
        args = plan.args
        validator = PlanStore(self.record_manager, self.draft_manager,
                              self.template_manager, args.get("batch_id"),
                              args.get("template_name"))
        if plan.action == "save_draft":
            validator._validate_batch(args.get("batch_id"), args.get("template_name"))
            validator._validate_template_fields(args.get("template_name"), args["data"])
            return {"draft_id": self.draft_manager.save_draft(
                args["draft_name"], args.get("batch_id"), args.get("template_name"), args["data"])}
        if plan.action == "create_record":
            template_id = self.template_manager.get_template_id(args["template_name"])
            if not template_id:
                raise ValueError("模板不存在")
            validator._validate_batch(args["batch_id"], args["template_name"])
            validator._validate_template_fields(args["template_name"], args["data"])
            if args.get("parent_id") and not self.record_manager.get_record(args["parent_id"]):
                raise ValueError("父记录不存在")
            record_id = self.record_manager.create_record(
                batch_id=args["batch_id"], template_id=template_id,
                template_name=args["template_name"], name=args["name"],
                filing_type=args.get("filing_type"), layer=args.get("layer", "item"),
                parent_id=args.get("parent_id"), year=args.get("year"), data=args["data"])
            return {"record_id": record_id}
        record = self.record_manager.get_record(args["record_id"])
        if not record:
            raise ValueError("目标记录已不存在")
        if record.get("review_status") != plan.snapshot.get("review_status"):
            raise ValueError("目标记录状态已变化，请重新检查并确认")
        if plan.action in {"update_record", "field_fill"}:
            validator._validate_record_fields(record, args["fields"])
            expected = plan.snapshot.get("values", {})
            current = record.get("values", {})
            changes = args["fields"]
            if any(current.get(key, "") != expected.get(key, "") for key in changes):
                raise ValueError("目标字段已变化，请重新检查并确认")
            if plan.action == "field_fill" and any(str(current.get(key, "")).strip() for key in changes):
                raise ValueError("目标字段已不为空，拒绝覆盖")
            self.record_manager.update_record(args["record_id"], changes)
            return {"record_id": args["record_id"], "updated_fields": list(changes)}
        if plan.action == "mark_reviewed":
            self.record_manager.update_record_status(args["record_id"], review_status="reviewed")
            return {"record_id": args["record_id"], "review_status": "reviewed"}
        raise ValueError("计划动作不受支持")

    @staticmethod
    def _log_type(action):
        return {"save_draft": "save_draft", "create_record": "save_record",
                "update_record": "update_record", "field_fill": "update_record",
                "mark_reviewed": "mark_reviewed"}[action]

    @staticmethod
    def _log_details(plan, result):
        details = {"agent_plan_id": plan.plan_id, "agent_approved": True}
        if "record_id" in result:
            details["record_id"] = result["record_id"]
        if "draft_id" in result:
            details["draft_id"] = result["draft_id"]
        if "updated_fields" in result:
            details["field_keys"] = result["updated_fields"]
        if plan.action == "save_draft":
            details["draft_name"] = plan.args["draft_name"]
        if plan.action == "create_record":
            details.update(record_name=plan.args["name"], template_name=plan.args["template_name"])
        return details
