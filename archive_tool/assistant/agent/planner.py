"""Validated, expiring approval plans. Creating a plan never touches SQLite."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from db.database import get_cursor
from core.validation import Validator


class PlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: int | None = None
    template_name: str | None = None
    name: str | None = Field(default=None, max_length=200)
    filing_type: str | None = None
    layer: str = "item"
    parent_id: int | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    record_id: int | None = None
    draft_id: int | None = None
    draft_name: str | None = Field(default=None, max_length=200)
    data: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)


@dataclass
class ExecutionPlan:
    plan_id: str
    action: str
    args: dict
    preview: dict
    reason: str
    citations: list[dict]
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = field(default_factory=lambda: (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
    snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


_ACTIONS = {"save_draft", "create_record", "update_record", "mark_reviewed", "field_fill"}


class PlanStore:
    def __init__(self, record_manager, draft_manager, template_manager, batch_id=None, template_name=None):
        self.record_manager = record_manager
        self.draft_manager = draft_manager
        self.template_manager = template_manager
        self.batch_id = batch_id
        self.template_name = template_name
        self.plans: dict[str, ExecutionPlan] = {}

    def propose(self, action: str, args: dict, reason: str = "模型根据当前问题提出的待确认操作。") -> ExecutionPlan:
        if action not in _ACTIONS or not isinstance(args, dict):
            raise ValueError("计划动作或参数无效")
        try:
            parsed = PlanArgs.model_validate(args)
        except ValidationError:
            raise ValueError("计划参数不符合要求") from None
        snapshot = {}
        values = parsed.model_dump(exclude_none=True)
        values["data"] = parsed.data
        values["fields"] = parsed.fields
        if action == "save_draft":
            values.setdefault("batch_id", self.batch_id)
            values.setdefault("template_name", self.template_name)
            if not values.get("draft_name") or not values["data"]:
                raise ValueError("草稿计划需要名称和字段数据")
            self._validate_batch(values.get("batch_id"), values.get("template_name"))
            self._validate_template_fields(values.get("template_name"), values["data"])
            preview = {"draft_name": values["draft_name"], "batch_id": values["batch_id"],
                       "template_name": values["template_name"], "field_count": len(values["data"])}
        elif action == "create_record":
            values.setdefault("batch_id", self.batch_id)
            values.setdefault("template_name", self.template_name)
            if not values.get("batch_id") or not values.get("template_name") or not values.get("name") or not values["data"]:
                raise ValueError("新建记录计划需要当前批次、模板、名称和字段数据")
            if values.get("filing_type") not in {None, "item", "volume"}:
                raise ValueError("归档类型无效")
            if not self.template_manager.get_template_id(values["template_name"]):
                raise ValueError("模板不存在")
            self._validate_batch(values["batch_id"], values["template_name"])
            self._validate_template_fields(values["template_name"], values["data"])
            if values.get("parent_id") and not self.record_manager.get_record(values["parent_id"]):
                raise ValueError("父记录不存在")
            preview = {"name": values["name"], "batch_id": values["batch_id"],
                       "template_name": values["template_name"], "fields": values["data"]}
        else:
            record_id = values.get("record_id")
            record = self.record_manager.get_record(record_id) if record_id else None
            if not record:
                raise ValueError("目标记录不存在")
            if action in {"update_record", "field_fill"}:
                changes = values.get("fields") or values.get("data")
                if not changes:
                    raise ValueError("更新计划没有字段变更")
                if action == "field_fill":
                    changes = {key: value for key, value in changes.items()
                               if not str(record.get("values", {}).get(key, "")).strip()}
                    if not changes:
                        raise ValueError("没有可填入的空字段")
                values["fields"] = changes
                preview = {"record_id": record_id,
                           "diff": {key: {"old": record.get("values", {}).get(key, ""), "new": value}
                                    for key, value in changes.items()}}
            else:
                preview = {"record_id": record_id, "old_status": record.get("review_status"),
                           "new_status": "reviewed"}
            if action in {"update_record", "field_fill"}:
                self._validate_record_fields(record, values.get("fields", {}))
            snapshot = {"review_status": record.get("review_status"), "values": record.get("values", {})}
        if action == "save_draft":
            snapshot = {}
        plan = ExecutionPlan(uuid4().hex, action, values, preview,
                             str(reason)[:500], [], snapshot=snapshot)
        self.plans[plan.plan_id] = plan
        return plan

    def _validate_record_fields(self, record, changes):
        template = self.template_manager.get_template_by_id(record.get("template_id"))
        field_map = {item["key"]: item for item in (template or {}).get("fields", [])}
        allowed = set(field_map)
        if not changes or any(key not in allowed for key in changes):
            raise ValueError("计划包含目标模板中不存在的字段")
        self._validate_values(field_map, changes)

    def _validate_template_fields(self, template_name, values):
        if not template_name:
            raise ValueError("计划缺少模板名称")
        template = self.template_manager.get_template_by_name(template_name)
        field_map = {item["key"]: item for item in (template or {}).get("fields", [])}
        allowed = set(field_map)
        if not values or any(key not in allowed for key in values):
            raise ValueError("计划包含模板中不存在的字段")
        self._validate_values(field_map, values)

    @staticmethod
    def _validate_values(field_map, values):
        if any(len(value) > 5000 for value in values.values()):
            raise ValueError("字段值超过安全长度")
        validator = Validator()
        for key, value in values.items():
            error = validator.validate_field(field_map[key], value)
            if error:
                raise ValueError(error.message)

    @staticmethod
    def _validate_batch(batch_id, template_name):
        if batch_id is None:
            return
        with get_cursor() as cursor:
            cursor.execute("SELECT template_name FROM batches WHERE id=?", (batch_id,))
            batch = cursor.fetchone()
        if not batch:
            raise ValueError("批次不存在")
        if batch["template_name"] and template_name and batch["template_name"] != template_name:
            raise ValueError("模板与目标批次不匹配")

    def get_pending(self):
        return [plan for plan in self.plans.values() if plan.status == "pending"]

    def update(self, plan_id, **changes):
        plan = self.plans.get(plan_id)
        if not plan or plan.status != "pending":
            raise ValueError("待确认计划不存在")
        citations = plan.citations
        updated = self.propose(plan.action, {**plan.args, **changes}, reason=plan.reason)
        del self.plans[updated.plan_id]
        self.plans.pop(plan.plan_id, None)
        updated.plan_id = plan.plan_id
        updated.citations = citations
        self.plans[plan.plan_id] = updated
        return updated

    def decide(self, plan_id, decision):
        if decision not in {"approved", "rejected"}:
            raise ValueError("计划决定无效")
        plan = self.plans.get(plan_id)
        if not plan or plan.status != "pending":
            raise ValueError("待确认计划不存在")
        plan.status = decision
        return plan
