"""Chinese-described, dependency-injected archive tools."""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from langchain_core.tools import StructuredTool

from assistant.generation import ask as ask_policy, suggest, verify_grounded_answer
from assistant.manual import ask_manual
from assistant.parsing import Parser
from core.draft_manager import DraftManager
from core.record_manager import RecordManager
from core.template_manager import TemplateManager
from db.database import get_cursor
from .planner import PlanStore


class QuestionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000, description="用户想核对的问题")
    scope: str = Field(default="通用", max_length=100, description="资料适用范围")


class ManualArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000, description="软件操作问题")


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(min_length=1, max_length=120, description="只用于本地档案检索")
    template_name: str | None = Field(default=None, max_length=100, description="可选模板范围")


class IdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: int = Field(gt=0, description="记录编号")


class BatchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: int = Field(gt=0, description="批次编号")


class TextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000, description="仅限用户明确提供且允许处理的脱敏文本")


class PlanArgsSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: int | None = Field(default=None, gt=0, description="目標批次编号；省略时使用当前批次")
    template_name: str | None = Field(default=None, max_length=100, description="模板名称；省略时使用当前模板")
    name: str | None = Field(default=None, max_length=200, description="新记录名称")
    filing_type: str | None = Field(default=None, description="仅允许 item 或 volume")
    layer: str = Field(default="item", description="记录层级")
    parent_id: int | None = Field(default=None, gt=0, description="可选父记录编号")
    year: int | None = Field(default=None, ge=1900, le=2200, description="档案年度")
    record_id: int | None = Field(default=None, gt=0, description="目标记录编号")
    draft_id: int | None = Field(default=None, gt=0, description="目标草稿编号")
    draft_name: str | None = Field(default=None, max_length=200, description="草稿名称")
    data: dict[str, str] = Field(default_factory=dict, description="新建记录或草稿的字段值，仅在用户授权外发时使用")
    fields: dict[str, str] = Field(default_factory=dict, description="更新的字段键值；仅填空工具不能覆盖已有字段")


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _safe_citations(citations):
    return [{key: value for key, value in citation.items()
             if key not in {"source"} and key not in {"path"}} |
            {"source": Path(str(citation.get("source", ""))).name,
             "page": citation.get("page"), "start_index": citation.get("start_index"),
             "quote": citation.get("quote", "")}
            for citation in citations]


def _database_citations(kind, rows, quote_for):
    return [{"id": f"db-{kind}-{row['id']}", "source": "本地档案数据库",
             "page": None, "start_index": None, "kind": "数据库",
             "quote": quote_for(row)} for row in rows]


def build_tools(index, service=None, record_manager=None, draft_manager=None,
                template_manager=None, batch_id=None, template_name=None,
                allow_model_calls=False, local_text=None):
    """Build tools for one dialog; no process-wide state or archive payloads."""
    records = record_manager or RecordManager()
    drafts = draft_manager or DraftManager()
    templates = template_manager or TemplateManager()
    plans = PlanStore(records, drafts, templates, batch_id, template_name)
    tools = []

    def add(name, description, schema, function):
        tools.append(StructuredTool.from_function(func=function, name=name,
            description=description, args_schema=schema))

    def policy(question: str, scope: str = "通用"):
        scope = template_name if scope == '通用' and template_name else scope
        embeddings = service if allow_model_calls and service and getattr(service, 'embedding_model', '') else None
        result = ask_policy(index, question, scope, embeddings=embeddings)
        result["citations"] = _safe_citations(result.get("citations", []))
        return _json(result)

    add("ask_policy", "按范围检索档案规范，按需使用已索引向量；回答逐句带引用并经本地支持校验，证据不足时拒答。", QuestionArgs, policy)

    def manual(question: str):
        embeddings = service if allow_model_calls and service and getattr(service, 'embedding_model', '') else None
        result = ask_manual(index, question, service=embeddings,
                            use_embeddings=bool(embeddings), mode="hybrid",
                            generate=False)
        result["citations"] = _safe_citations(result.get("citations", []))
        return _json(result)

    add("ask_manual", "检索本软件操作指南，只返回指南中逐字核验的步骤和出处；不执行操作。", ManualArgs, manual)

    def search_records(keyword: str, template_name: str | None = None):
        with get_cursor() as cursor:
            sql = """SELECT DISTINCT r.id, r.batch_id, r.template_name, r.year,
                       r.filing_type, r.review_status, r.upload_status
                FROM records r LEFT JOIN record_values v ON v.record_id=r.id
                WHERE (COALESCE(r.name,'') LIKE ? OR COALESCE(v.field_value,'') LIKE ?)"""
            params = [f"%{keyword}%", f"%{keyword}%"]
            if batch_id:
                sql += " AND r.batch_id=?"
                params.append(batch_id)
            if template_name:
                sql += " AND r.template_name=?"
                params.append(template_name)
            sql += " ORDER BY r.id DESC LIMIT 50"
            rows = [dict(row) for row in cursor.execute(sql, params).fetchall()]
        citations = _database_citations("search", rows, lambda row:
            f"记录编号 {row['id']}；批次 {row.get('batch_id')}；年度 {row.get('year')}；审核状态 {row.get('review_status')}；上传状态 {row.get('upload_status')}。")
        citations.append({'id': 'db-search-count', 'kind': '数据库', 'source': '本地检索元数据',
                          'quote': f'本次检索返回 {len(rows)} 条记录；返回上限 50 条，不代表全部匹配总数。'})
        return _json({"count": len(rows), "records": rows, "citations": citations, "limit": 50,
                      "privacy": "字段值与名称未返回给模型"})

    add("search_records", "在本地按关键词查档案；只返回编号、批次、模板、年度和状态，不返回记录名称或字段值。最多 50 条。", SearchArgs, search_records)

    def get_record_detail(record_id: int):
        record = records.get_record(record_id)
        if not record:
            return _json({"error": "记录不存在"})
        safe = {key: record.get(key) for key in
            ("id", "batch_id", "template_id", "template_name", "filing_type", "layer",
             "parent_id", "year", "review_status", "upload_status", "created_at", "updated_at")}
        safe["citations"] = _database_citations("record", [safe], lambda row:
            f"记录编号 {row['id']}；审核状态 {row.get('review_status')}；上传状态 {row.get('upload_status')}；年度 {row.get('year')}。")
        return _json(safe)

    add("get_record_detail", "读取档案安全元数据；不得返回题名和任何字段值。", IdArgs, get_record_detail)

    def list_records(batch_id: int):
        rows = records.get_records_by_batch(batch_id)
        safe = [{key: row.get(key) for key in
                 ("id", "batch_id", "template_id", "template_name", "filing_type", "layer",
                  "parent_id", "year", "review_status", "upload_status")}
                for row in rows[:100]]
        citations = _database_citations("batch", safe, lambda row:
            f"记录编号 {row['id']}；批次 {row.get('batch_id')}；年度 {row.get('year')}；审核状态 {row.get('review_status')}。")
        citations.append({'id': f'db-batch-{batch_id}-count', 'kind': '数据库', 'source': '本地批次元数据',
                          'quote': f'批次 {batch_id} 共有 {len(rows)} 条记录；本次最多展示 100 条。'})
        return _json({"records": safe, "citations": citations, "count": len(rows), "limit": 100})

    add("list_records", "列出指定批次档案的安全元数据；档案名称和字段值留在本机。最多返回 100 条。", BatchArgs, list_records)

    def list_drafts(batch_id: int):
        rows = drafts.get_drafts_by_batch(batch_id)
        safe = [{key: row.get(key) for key in
                 ("id", "batch_id", "record_id", "template_name", "created_at")}
                | {"field_count": len(row.get("draft_data", {}))} for row in rows[:100]]
        citations = [{"id": f"db-draft-{row['id']}", "source": "本地草稿数据库",
                      "page": None, "start_index": None, "kind": "数据库",
                      "quote": f"草稿编号 {row['id']}；所属批次 {row.get('batch_id')}；字段数量 {row.get('field_count')}。"}
                     for row in safe]
        citations.append({'id': f'db-drafts-{batch_id}-count', 'kind': '数据库', 'source': '本地草稿元数据',
                          'quote': f'批次 {batch_id} 共有 {len(rows)} 条草稿；本次最多展示 100 条。'})
        return _json({"drafts": safe, "citations": citations, "count": len(rows), "limit": 100,
                      "privacy": "草稿字段内容未返回给模型"})

    add("list_drafts", "列出批次草稿的编号、名称、模板和字段数量；绝不返回草稿正文。", BatchArgs, list_drafts)

    def kb_sources():
        rows = []
        expected = (getattr(service, "model_name", None)
                    if allow_model_calls and service and service.embedding_model else None)
        for source in index.sources():
            state = index.vector_state(source["path"], expected_model=expected)["state"]
            rows.append({"name": Path(source["path"]).name, "kind": source["kind"],
                         "scope": source["scope"], "imported": source["imported"],
                         "vector_state": state})
        citations = [{'id': 'kb-source-count', 'source': '本地知识库元数据', 'kind': '元数据',
                      'quote': f'知识库共有 {len(rows)} 份资料。'}]
        for i, row in enumerate(rows):
            citations.append({'id': f'kb-source-{i}', 'source': '本地知识库元数据', 'kind': '元数据',
                'quote': f"资料文件名 {row['name']}；类别 {row['kind']}；适用范围 {row['scope']}；向量状态 {row['vector_state']}。"})
        return _json({"sources": rows, 'citations': citations})

    add("kb_sources", "列出知识库资料类别、适用范围和向量状态；隐藏完整本地路径。", None, kb_sources)

    def suggest_fields_from_text(text: str):
        if not allow_model_calls:
            raise PermissionError("字段原文只在本机处理")
        from langchain_core.documents import Document
        fields = templates.get_fields(template_name) if template_name else []
        if not fields:
            return _json({"suggestions": [], "notice": "当前模板没有可建议字段"})
        result = suggest([Document(page_content=text, metadata={
            "source": "用户提供的脱敏文本", "page": 1, "start_index": 0})], fields)
        return _json({"suggestions": result})
    add("suggest_fields_from_text", "从用户明确提供并同意发送的脱敏文本中抽取当前模板的题名、日期和责任者建议，并附原文出处；本地扫描件及已保存档案字段不会自动提供给模型。", TextArgs, suggest_fields_from_text)

    def plan_tool(action):
        def create_plan(**values):
            plan = plans.propose(action, values)
            preview = plan.preview
            safe_preview = {key: value for key, value in preview.items()
                            if key not in {"fields", "diff", "data", "name", "draft_name"}}
            changed = preview.get("diff", {}).keys()
            if changed:
                safe_preview.update(field_keys=list(changed), field_count=len(changed))
            if "fields" in preview:
                safe_preview.update(field_count=len(preview["fields"]))
            return _json({"status": "pending", "plan_id": plan.plan_id,
                          "action": plan.action, "preview": safe_preview,
                          "reason": plan.reason,
                          "notice": "待用户确认；当前没有执行任何数据库写操作"})
        return create_plan

    for name, action, description in (
        ("propose_save_draft", "save_draft", "只创建待确认草稿计划；草稿保存前不会写数据库，拒绝、关闭或超时均零写入。"),
        ("propose_create_record", "create_record", "只创建待确认的新档案计划；不执行创建，不调用删除或上传操作。"),
        ("propose_update_record", "update_record", "只创建待确认的记录字段更新计划；本地界面显示旧值与新值差异，已有值可能被覆盖。"),
        ("propose_mark_reviewed", "mark_reviewed", "只创建待确认的单条记录标记已核对计划；状态修改前需要用户确认。"),
        ("propose_field_fill", "field_fill", "只提出待确认的空字段回填计划；已有值会跳过，不允许覆盖。"),
    ):
        add(name, description, PlanArgsSchema, plan_tool(action))

    return tools, plans
