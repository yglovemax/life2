import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    AdminSession,
    AdminSessionStatus,
    AdminUser,
    AppApiKey,
    AppKeyStatus,
    AuditEvent,
    CallTrace,
    FieldContract,
    Issue,
    IssueStatus,
    KnowledgeChunk,
    KnowledgeSource,
    ModelConfig,
    Module,
    ModuleStatus,
    ModuleVersion,
    Page,
    PromptTemplate,
    utc_now,
)


PROMPT_KEYS = [
    "shared_prefix",
    "module_rules",
    "algorithm_data_template",
    "user_preferences_template",
    "final_request_template",
]

APP_ACTIVE_STATUSES = {ModuleStatus.gray.value, ModuleStatus.live.value}
ADMIN_SESSION_DAYS = 7
PASSWORD_ITERATIONS = 120000

DEMO_TEST_USERS = [
    {
        "id": "demo_user_001",
        "name": "Max / 白羊样本",
        "birth_profile": {
            "nickname": "max",
            "birth_date": "1989-09-29",
            "birth_time": "16:00",
            "birth_city": "兰州",
            "sun_sign": "天秤座",
            "moon_sign": "处女座",
            "rising_sign": "摩羯座",
        },
        "preferences": {
            "tone": "温暖、清晰、不过度玄学化",
            "density": "中等",
        },
    },
    {
        "id": "demo_user_002",
        "name": "Ava / 日运样本",
        "birth_profile": {
            "nickname": "Ava",
            "birth_date": "1996-04-12",
            "birth_time": "09:30",
            "birth_city": "上海",
            "sun_sign": "白羊座",
            "moon_sign": "巨蟹座",
            "rising_sign": "双子座",
        },
        "preferences": {
            "tone": "直接、有行动建议",
            "density": "低",
        },
    },
]


def list_modules(session: Session) -> list[dict]:
    modules = session.scalars(
        select(Module)
        .options(joinedload(Module.page), joinedload(Module.model), selectinload(Module.calls), selectinload(Module.issues))
        .order_by(Module.page_id, Module.id)
    ).all()
    rows: list[dict] = []
    for module in modules:
        today_calls = len(module.calls)
        fallback_count = sum(1 for call in module.calls if call.fallback_triggered)
        cost_cents = sum(call.estimated_cost_cents for call in module.calls)
        rows.append(
            {
                "id": module.id,
                "slug": module.slug,
                "name": module.name,
                "page_name": module.page.name,
                "owner": module.owner,
                "model": module.model.display_name if module.model else "未配置",
                "version": module.version,
                "status": module.status,
                "today_calls": today_calls,
                "today_cost_cents": cost_cents,
                "error_rate": 0,
                "fallback_count": fallback_count,
                "open_issues": sum(1 for issue in module.issues if issue.status != "resolved"),
                "updated_at": module.updated_at.isoformat(),
            }
        )
    return rows


def list_pages(session: Session) -> list[dict]:
    pages = session.scalars(select(Page).order_by(Page.id)).all()
    return [
        {
            "id": page.id,
            "slug": page.slug,
            "name": page.name,
            "description": page.description,
        }
        for page in pages
    ]


def list_models(session: Session) -> list[dict]:
    models = session.scalars(select(ModelConfig).order_by(ModelConfig.id)).all()
    return [
        {
            "id": model.id,
            "provider": model.provider,
            "name": model.name,
            "display_name": model.display_name,
            "quality_tier": model.quality_tier,
            "input_cost_per_1m": model.input_cost_per_1m,
            "output_cost_per_1m": model.output_cost_per_1m,
            "is_active": model.is_active,
        }
        for model in models
    ]


def list_test_users() -> list[dict]:
    return DEMO_TEST_USERS


def create_knowledge_source(session: Session, payload: dict) -> dict:
    title = (payload.get("title") or "未命名资料").strip()
    content = payload.get("content") or ""
    tags = normalize_tags(payload.get("tags") or [])
    source = KnowledgeSource(
        title=title,
        source_type=payload.get("source_type") or "markdown",
        content=content,
        tags=tags,
        status="active",
    )
    session.add(source)
    session.flush()

    chunks = chunk_markdown(title, content)
    for index, chunk in enumerate(chunks, start=1):
        session.add(
            KnowledgeChunk(
                source_id=source.id,
                title=chunk["title"],
                content=chunk["content"],
                tags=tags,
                chunk_index=index,
            )
        )
    source.chunk_count = len(chunks)
    session.commit()
    session.refresh(source)
    return serialize_source(source)


def create_manual_knowledge_entry(session: Session, payload: dict) -> dict:
    source_payload = {
        "title": payload.get("title") or "人工知识条目",
        "source_type": "manual",
        "content": payload.get("content") or "",
        "tags": payload.get("tags") or [],
    }
    source_data = create_knowledge_source(session, source_payload)
    chunks = list_knowledge_chunks(session, tag=None, source_id=source_data["id"])
    return chunks[0] if chunks else source_data


def list_knowledge_sources(session: Session) -> list[dict]:
    sources = session.scalars(select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc())).all()
    return [serialize_source(source) for source in sources]


def list_knowledge_chunks(session: Session, tag: str | None = None, source_id: int | None = None) -> list[dict]:
    chunks = session.scalars(select(KnowledgeChunk).order_by(KnowledgeChunk.created_at.desc())).all()
    rows = [serialize_chunk(chunk) for chunk in chunks]
    if source_id is not None:
        rows = [row for row in rows if row["source_id"] == source_id]
    if tag:
        rows = [row for row in rows if tag in row["tags"]]
    return rows


def search_knowledge(session: Session, payload: dict) -> list[dict]:
    query = (payload.get("query") or "").strip().lower()
    tags = normalize_tags(payload.get("tags") or [])
    limit = int(payload.get("limit") or 8)
    chunks = list_knowledge_chunks(session)
    scored: list[tuple[int, dict]] = []
    for chunk in chunks:
        if tags and not set(tags).intersection(set(chunk["tags"])):
            continue
        haystack = f"{chunk['title']}\n{chunk['content']}".lower()
        score = 0
        if query and query in haystack:
            score += 5
        score += len(set(tags).intersection(set(chunk["tags"])))
        if not query and score == 0 and tags:
            score = 1
        if score > 0 or (not query and not tags):
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]]


def retrieve_knowledge_hits(session: Session, tags: list, input_payload: dict, limit: int = 3) -> list[dict]:
    query_terms = [
        input_payload.get("sun_sign"),
        input_payload.get("moon_sign"),
        input_payload.get("rising_sign"),
        input_payload.get("topic"),
    ]
    query = " ".join(str(term) for term in query_terms if term)
    hits = search_knowledge(session, {"query": query, "tags": tags, "limit": limit})
    if not hits and tags:
        hits = search_knowledge(session, {"query": "", "tags": tags, "limit": limit})
    return hits


def serialize_source(source: KnowledgeSource) -> dict:
    return {
        "id": source.id,
        "title": source.title,
        "source_type": source.source_type,
        "status": source.status,
        "tags": source.tags,
        "chunk_count": source.chunk_count,
        "created_at": source.created_at.isoformat(),
    }


def serialize_chunk(chunk: KnowledgeChunk) -> dict:
    return {
        "id": chunk.id,
        "source_id": chunk.source_id,
        "title": chunk.title,
        "content": chunk.content,
        "tags": chunk.tags,
        "chunk_index": chunk.chunk_index,
        "created_at": chunk.created_at.isoformat(),
    }


def normalize_tags(tags: list | str) -> list[str]:
    if isinstance(tags, str):
        candidates = tags.replace("，", ",").split(",")
    else:
        candidates = tags
    return [str(tag).strip() for tag in candidates if str(tag).strip()]


def chunk_markdown(default_title: str, content: str) -> list[dict]:
    chunks: list[dict] = []
    current_title = default_title
    current_lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            if current_lines:
                chunks.extend(chunk_paragraphs(current_title, "\n".join(current_lines)))
                current_lines = []
            current_title = line.lstrip("#").strip() or default_title
        elif line:
            current_lines.append(line)
        else:
            if current_lines:
                chunks.extend(chunk_paragraphs(current_title, "\n".join(current_lines)))
                current_lines = []
    if current_lines:
        chunks.extend(chunk_paragraphs(current_title, "\n".join(current_lines)))
    if not chunks and content.strip():
        chunks.append({"title": default_title, "content": content.strip()})
    return chunks or [{"title": default_title, "content": ""}]


def chunk_paragraphs(title: str, text: str) -> list[dict]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    return [{"title": title, "content": paragraph} for paragraph in paragraphs]


def get_module_detail(session: Session, module_id: int) -> dict | None:
    module = session.scalar(
        select(Module)
        .where(Module.id == module_id)
        .options(
            joinedload(Module.page),
            joinedload(Module.model),
            joinedload(Module.prompt),
            selectinload(Module.fields),
            selectinload(Module.calls),
            selectinload(Module.issues),
            selectinload(Module.versions),
        )
    )
    if module is None:
        return None

    prompt = module.prompt or PromptTemplate(module_id=module.id)
    calls = sorted(module.calls, key=lambda call: call.created_at, reverse=True)[:10]
    return {
        "id": module.id,
        "page_id": module.page_id,
        "model_id": module.model_id,
        "slug": module.slug,
        "name": module.name,
        "page_name": module.page.name,
        "owner": module.owner,
        "model": module.model.display_name if module.model else "未配置",
        "version": module.version,
        "status": module.status,
        "fallback_content": module.fallback_content,
        "algorithm_fields": module.algorithm_fields,
        "knowledge_tags": module.knowledge_tags,
        "prompt": {
            "shared_prefix": prompt.shared_prefix,
            "module_rules": prompt.module_rules,
            "algorithm_data_template": prompt.algorithm_data_template,
            "user_preferences_template": prompt.user_preferences_template,
            "final_request_template": prompt.final_request_template,
            "version": prompt.version,
        },
        "fields": [serialize_field(field) for field in module.fields],
        "recent_calls": [serialize_call(call) for call in calls],
        "versions": [serialize_version(version) for version in sorted(module.versions, key=lambda item: (item.created_at, item.id), reverse=True)],
        "issues": [
            serialize_issue(issue, module=module)
            for issue in sorted(module.issues, key=lambda item: (item.status == IssueStatus.resolved.value, item.created_at), reverse=False)
        ],
    }


def serialize_version(version: ModuleVersion) -> dict:
    return {
        "id": version.id,
        "module_id": version.module_id,
        "version": version.version,
        "status": version.status,
        "snapshot": version.snapshot,
        "created_at": version.created_at.isoformat(),
    }


def serialize_field(field: FieldContract) -> dict:
    return {
        "id": field.id,
        "field_name": field.field_name,
        "purpose": field.purpose,
        "display_position": field.display_position,
        "example": field.example,
        "source": field.source,
        "is_ai_generated": field.is_ai_generated,
        "is_required": field.is_required,
        "owner": field.owner,
        "status": field.status,
        "change_log": field.change_log,
    }


def create_module(session: Session, payload: dict) -> dict:
    page_id = int(payload["page_id"])
    model_id = payload.get("model_id")
    module = Module(
        page_id=page_id,
        model_id=int(model_id) if model_id else None,
        slug=payload["slug"].strip(),
        name=payload["name"].strip(),
        owner=payload.get("owner") or "未分配",
        status=payload.get("status") or "draft",
        fallback_content=payload.get("fallback_content") or "",
        algorithm_fields=payload.get("algorithm_fields") or {},
        knowledge_tags=payload.get("knowledge_tags") or [],
    )
    session.add(module)
    session.flush()
    session.add(build_prompt(module.id, payload.get("prompt") or {}))
    for field_payload in payload.get("fields") or []:
        session.add(build_field(module.id, field_payload))
    session.commit()
    return get_module_detail(session, module.id) or {}


def update_module(session: Session, module_id: int, payload: dict) -> dict | None:
    module = session.scalar(
        select(Module)
        .where(Module.id == module_id)
        .options(joinedload(Module.prompt), selectinload(Module.fields))
    )
    if module is None:
        return None

    module.page_id = int(payload["page_id"])
    model_id = payload.get("model_id")
    module.model_id = int(model_id) if model_id else None
    module.slug = payload["slug"].strip()
    module.name = payload["name"].strip()
    module.owner = payload.get("owner") or "未分配"
    module.status = payload.get("status") or "draft"
    module.fallback_content = payload.get("fallback_content") or ""
    module.algorithm_fields = payload.get("algorithm_fields") or {}
    module.knowledge_tags = payload.get("knowledge_tags") or []

    prompt_payload = payload.get("prompt") or {}
    if module.prompt is None:
        module.prompt = build_prompt(module.id, prompt_payload)
    else:
        for key in PROMPT_KEYS:
            setattr(module.prompt, key, prompt_payload.get(key) or "")
        module.prompt.version += 1

    module.fields.clear()
    session.flush()
    for field_payload in payload.get("fields") or []:
        module.fields.append(build_field(module.id, field_payload))

    session.commit()
    return get_module_detail(session, module.id)


def build_prompt(module_id: int, payload: dict) -> PromptTemplate:
    values = {key: payload.get(key) or "" for key in PROMPT_KEYS}
    return PromptTemplate(module_id=module_id, **values)


def build_field(module_id: int, payload: dict) -> FieldContract:
    return FieldContract(
        module_id=module_id,
        field_name=(payload.get("field_name") or "").strip(),
        purpose=payload.get("purpose") or "",
        display_position=payload.get("display_position") or "",
        example=payload.get("example") or "",
        source=payload.get("source") or "ai",
        is_ai_generated=payload.get("is_ai_generated", True),
        is_required=payload.get("is_required", True),
        owner=payload.get("owner") or "未分配",
        status=payload.get("status") or "draft",
        change_log=payload.get("change_log") or "",
    )


def serialize_call(call: CallTrace) -> dict:
    return {
        "id": call.id,
        "module_id": call.module_id,
        "request_type": call.request_type,
        "input_payload": call.input_payload,
        "model_request": call.model_request,
        "model_raw_response": call.model_raw_response,
        "final_json": call.final_json,
        "status": call.status,
        "fallback_triggered": call.fallback_triggered,
        "fallback_reason": call.fallback_reason,
        "prompt_version": call.prompt_version,
        "model_name": call.model_name,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "estimated_cost_cents": call.estimated_cost_cents,
        "manual_score": call.manual_score,
        "reviewer_notes": call.reviewer_notes,
        "knowledge_hits": call.knowledge_hits or [],
        "created_at": call.created_at.isoformat(),
    }


def run_module_test(session: Session, module_id: int, payload: dict) -> dict | None:
    module = session.scalar(
        select(Module)
        .where(Module.id == module_id)
        .options(joinedload(Module.page), joinedload(Module.model), joinedload(Module.prompt), selectinload(Module.fields))
    )
    if module is None:
        return None
    return run_module_trace(session, module, payload, request_type="test", allow_model_override=True)


def run_module_trace(session: Session, module: Module, payload: dict, request_type: str, allow_model_override: bool = False) -> dict:
    prompt = module.prompt or PromptTemplate(module_id=module.id)
    model_name = module.model.display_name if module.model else "未配置"
    if allow_model_override and payload.get("model_id"):
        override_model = session.get(ModelConfig, int(payload["model_id"]))
        if override_model is not None:
            model_name = override_model.display_name
    input_payload = payload.get("input_payload") or {}
    knowledge_hits = retrieve_knowledge_hits(session, module.knowledge_tags or [], input_payload)
    model_request = "\n\n".join(
        [
            prompt.shared_prefix,
            prompt.module_rules,
            f"算法数据: {input_payload}",
            f"知识库命中: {knowledge_hits}",
            prompt.user_preferences_template,
            prompt.final_request_template,
        ]
    )
    force_fallback = bool(payload.get("force_fallback"))
    fallback_reason = payload.get("fallback_reason") or "forced_fallback"
    if force_fallback:
        summary = module.fallback_content or f"{module.name}暂时使用备用内容，请稍后重试。"
        final_json = {
            "module_id": module.id,
            "module_slug": module.slug,
            "title": module.name,
            "summary": summary,
            "fallback": True,
            "fallback_reason": fallback_reason,
            "knowledge_hits": knowledge_hits,
        }
        raw_response = {
            "fallback": True,
            "reason": fallback_reason,
            "summary": summary,
        }
        status = "fallback"
    else:
        caller = payload.get("test_user") or payload.get("user_id") or "测试用户"
        output_label = "正式输出" if request_type == "official" else "测试输出"
        summary = f"{module.name}{output_label}：已根据 {caller} 和 {payload.get('date', '未指定日期')} 生成内容。"
        final_json = {
            "module_id": module.id,
            "module_slug": module.slug,
            "title": module.name,
            "summary": summary,
            "fields": {field.field_name: field.example for field in module.fields},
            "knowledge_hits": knowledge_hits,
        }
        raw_response = {
            "title": module.name,
            "summary": summary,
        }
        status = "ok"
    input_tokens = max(1, len(model_request) // 4)
    output_tokens = max(1, len(str(raw_response)) // 4)
    trace = CallTrace(
        module_id=module.id,
        request_type=request_type,
        input_payload=payload,
        model_request=model_request,
        model_raw_response=str(raw_response),
        final_json=final_json,
        status=status,
        fallback_triggered=force_fallback,
        fallback_reason=fallback_reason if force_fallback else "",
        prompt_version=prompt.version,
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_cents=estimate_cost_cents(input_tokens, output_tokens),
        knowledge_hits=knowledge_hits,
    )
    session.add(trace)
    session.commit()
    session.refresh(trace)
    return serialize_call(trace)


def run_batch_tests(session: Session, payload: dict) -> list[dict]:
    traces = []
    for module_id in payload.get("module_ids") or []:
        trace = run_module_test(session, int(module_id), payload)
        if trace is not None:
            traces.append(trace)
    return traces


def score_call_trace(session: Session, trace_id: int, payload: dict) -> dict | None:
    trace = session.get(CallTrace, trace_id)
    if trace is None:
        return None
    score = payload.get("manual_score")
    trace.manual_score = int(score) if score is not None else None
    trace.reviewer_notes = payload.get("reviewer_notes") or ""
    session.commit()
    session.refresh(trace)
    return serialize_call(trace)


def create_issue(session: Session, module_id: int, payload: dict) -> dict | None:
    module = session.get(Module, module_id)
    if module is None:
        return None
    issue = Issue(
        module_id=module.id,
        title=(payload.get("title") or "未命名问题").strip(),
        issue_type=(payload.get("issue_type") or "content_quality").strip(),
        owner=(payload.get("owner") or "未分配").strip(),
        status=normalize_issue_status(payload.get("status") or IssueStatus.open.value),
        notes=payload.get("notes") or "",
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return serialize_issue(issue, module=module)


def update_issue(session: Session, issue_id: int, payload: dict) -> dict | None:
    issue = session.scalar(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(joinedload(Issue.module).joinedload(Module.page))
    )
    if issue is None:
        return None
    if "title" in payload:
        issue.title = (payload.get("title") or issue.title).strip()
    if "issue_type" in payload:
        issue.issue_type = (payload.get("issue_type") or issue.issue_type).strip()
    if "owner" in payload:
        issue.owner = (payload.get("owner") or "未分配").strip()
    if "status" in payload:
        issue.status = normalize_issue_status(payload.get("status"))
    if "notes" in payload:
        issue.notes = payload.get("notes") or ""
    session.commit()
    session.refresh(issue)
    return serialize_issue(issue)


def list_issues(session: Session, status: str | None = None, owner: str | None = None, module_id: int | None = None) -> list[dict]:
    statement = select(Issue).options(joinedload(Issue.module).joinedload(Module.page)).order_by(Issue.created_at.desc(), Issue.id.desc())
    if status:
        statement = statement.where(Issue.status == normalize_issue_status(status))
    if owner:
        statement = statement.where(Issue.owner == owner)
    if module_id is not None:
        statement = statement.where(Issue.module_id == module_id)
    issues = session.scalars(statement).all()
    return [serialize_issue(issue) for issue in issues]


def normalize_issue_status(status: str | None) -> str:
    allowed = {item.value for item in IssueStatus}
    return status if status in allowed else IssueStatus.open.value


def serialize_issue(issue: Issue, module: Module | None = None) -> dict:
    resolved_module = module or issue.module
    return {
        "id": issue.id,
        "module_id": issue.module_id,
        "module_name": resolved_module.name if resolved_module else "",
        "page_name": resolved_module.page.name if resolved_module and resolved_module.page else "",
        "title": issue.title,
        "issue_type": issue.issue_type,
        "owner": issue.owner,
        "status": issue.status,
        "notes": issue.notes,
        "created_at": issue.created_at.isoformat(),
    }


def list_call_traces(session: Session, limit: int = 20, request_type: str | None = None) -> list[dict]:
    statement = select(CallTrace).order_by(CallTrace.created_at.desc()).limit(limit)
    if request_type:
        statement = select(CallTrace).where(CallTrace.request_type == request_type).order_by(CallTrace.created_at.desc()).limit(limit)
    traces = session.scalars(statement).all()
    return [serialize_call(trace) for trace in traces]


def render_app_module(session: Session, module_slug: str, payload: dict, request_id: str | None = None) -> dict | None:
    module = session.scalar(
        select(Module)
        .where(Module.slug == module_slug)
        .options(joinedload(Module.page), joinedload(Module.model), joinedload(Module.prompt), selectinload(Module.fields))
    )
    if module is None or module.status not in APP_ACTIVE_STATUSES:
        return None

    resolved_request_id = request_id or new_request_id()
    trace_payload = {**payload, "request_id": resolved_request_id}
    trace = run_module_trace(session, module, trace_payload, request_type="official", allow_model_override=False)
    return app_module_response(module, trace, resolved_request_id)


def render_app_page(session: Session, page_slug: str, payload: dict) -> dict | None:
    page = session.scalar(
        select(Page)
        .where(Page.slug == page_slug)
        .options(
            selectinload(Page.modules).joinedload(Module.model),
            selectinload(Page.modules).joinedload(Module.prompt),
            selectinload(Page.modules).selectinload(Module.fields),
        )
    )
    if page is None:
        return None

    request_id = new_request_id()
    modules = sorted((module for module in page.modules if module.status in APP_ACTIVE_STATUSES), key=lambda module: module.id)
    rendered_modules = []
    for module in modules:
        trace = run_module_trace(session, module, {**payload, "request_id": request_id}, "official")
        rendered_modules.append(app_module_response(module, trace, request_id))
    return {
        "request_id": request_id,
        "page": {
            "id": page.id,
            "slug": page.slug,
            "name": page.name,
        },
        "modules": rendered_modules,
        "meta": {
            "request_type": "official",
            "module_count": len(rendered_modules),
        },
    }


def app_module_response(module: Module, trace: dict, request_id: str) -> dict:
    return {
        "request_id": request_id,
        "trace_id": trace["id"],
        "module": {
            "id": module.id,
            "slug": module.slug,
            "name": module.name,
            "page_slug": module.page.slug if module.page else "",
            "page_name": module.page.name if module.page else "",
            "version": module.version,
            "status": module.status,
        },
        "result": trace["final_json"],
        "meta": {
            "request_type": trace["request_type"],
            "model_name": trace["model_name"],
            "prompt_version": trace["prompt_version"],
            "estimated_cost_cents": trace["estimated_cost_cents"],
        },
    }


def new_request_id() -> str:
    return f"req_{uuid4().hex[:18]}"


def cost_summary(session: Session) -> dict:
    traces = session.scalars(
        select(CallTrace)
        .options(joinedload(CallTrace.module).joinedload(Module.page))
        .order_by(CallTrace.created_at.desc())
    ).all()
    by_page: dict[str, dict] = {}
    by_module: dict[int, dict] = {}
    by_model: dict[str, dict] = {}

    for trace in traces:
        cost = trace.estimated_cost_cents or 0
        module = trace.module
        page_name = module.page.name if module and module.page else "未分组页面"
        module_id = module.id if module else trace.module_id
        module_name = module.name if module else f"模块 {trace.module_id}"
        model_name = trace.model_name or "未配置"

        page_row = by_page.setdefault(page_name, {"page_name": page_name, "calls": 0, "cost_cents": 0, "fallback_count": 0})
        page_row["calls"] += 1
        page_row["cost_cents"] += cost
        page_row["fallback_count"] += int(trace.fallback_triggered)

        module_row = by_module.setdefault(
            module_id,
            {"module_id": module_id, "module_name": module_name, "page_name": page_name, "calls": 0, "cost_cents": 0, "fallback_count": 0},
        )
        module_row["calls"] += 1
        module_row["cost_cents"] += cost
        module_row["fallback_count"] += int(trace.fallback_triggered)

        model_row = by_model.setdefault(model_name, {"model_name": model_name, "calls": 0, "cost_cents": 0, "fallback_count": 0})
        model_row["calls"] += 1
        model_row["cost_cents"] += cost
        model_row["fallback_count"] += int(trace.fallback_triggered)

    return {
        "total_calls": len(traces),
        "total_cost_cents": sum(trace.estimated_cost_cents or 0 for trace in traces),
        "fallback_calls": sum(1 for trace in traces if trace.fallback_triggered),
        "by_page": sorted(by_page.values(), key=lambda item: item["cost_cents"], reverse=True),
        "by_module": sorted(by_module.values(), key=lambda item: item["cost_cents"], reverse=True),
        "by_model": sorted(by_model.values(), key=lambda item: item["cost_cents"], reverse=True),
    }


def list_fallback_alerts(session: Session, limit: int = 30) -> list[dict]:
    traces = session.scalars(
        select(CallTrace)
        .where(CallTrace.fallback_triggered.is_(True))
        .options(joinedload(CallTrace.module).joinedload(Module.page))
        .order_by(CallTrace.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "trace_id": trace.id,
            "module_id": trace.module_id,
            "module_name": trace.module.name if trace.module else f"模块 {trace.module_id}",
            "page_name": trace.module.page.name if trace.module and trace.module.page else "未分组页面",
            "reason": trace.fallback_reason,
            "status": trace.status,
            "model_name": trace.model_name,
            "created_at": trace.created_at.isoformat(),
            "final_json": trace.final_json,
        }
        for trace in traces
    ]


def list_module_versions(session: Session, module_id: int) -> list[dict] | None:
    if session.get(Module, module_id) is None:
        return None
    versions = session.scalars(
        select(ModuleVersion)
        .where(ModuleVersion.module_id == module_id)
        .order_by(ModuleVersion.created_at.desc(), ModuleVersion.id.desc())
    ).all()
    return [serialize_version(version) for version in versions]


def publish_module(session: Session, module_id: int, payload: dict) -> dict | None:
    module = load_module_for_release(session, module_id)
    if module is None:
        return None

    next_status = payload.get("status") or ModuleStatus.gray.value
    allowed_statuses = {
        ModuleStatus.pending_test.value,
        ModuleStatus.test_passed.value,
        ModuleStatus.pending_approval.value,
        ModuleStatus.gray.value,
        ModuleStatus.live.value,
        ModuleStatus.disabled.value,
    }
    if next_status not in allowed_statuses:
        next_status = ModuleStatus.gray.value

    module.version += 1
    module.status = next_status
    session.add(
        ModuleVersion(
            module_id=module.id,
            version=module.version,
            status=module.status,
            snapshot=module_release_snapshot(module, payload, action="publish"),
        )
    )
    session.commit()
    return get_module_detail(session, module.id)


def rollback_module(session: Session, module_id: int, payload: dict) -> dict | None:
    module = load_module_for_release(session, module_id)
    if module is None:
        return None

    module.version += 1
    module.status = ModuleStatus.rolled_back.value
    session.add(
        ModuleVersion(
            module_id=module.id,
            version=module.version,
            status=module.status,
            snapshot=module_release_snapshot(module, payload, action="rollback"),
        )
    )
    session.commit()
    return get_module_detail(session, module.id)


def load_module_for_release(session: Session, module_id: int) -> Module | None:
    return session.scalar(
        select(Module)
        .where(Module.id == module_id)
        .options(joinedload(Module.prompt), selectinload(Module.fields), joinedload(Module.page), joinedload(Module.model), selectinload(Module.versions))
    )


def module_release_snapshot(module: Module, payload: dict, action: str) -> dict:
    prompt = module.prompt or PromptTemplate(module_id=module.id)
    return {
        "action": action,
        "operator": payload.get("operator") or "admin",
        "notes": payload.get("notes") or "",
        "reason": payload.get("reason") or "",
        "target_version": payload.get("target_version"),
        "module": {
            "id": module.id,
            "slug": module.slug,
            "name": module.name,
            "page_id": module.page_id,
            "page_name": module.page.name if module.page else "",
            "model_id": module.model_id,
            "model_name": module.model.display_name if module.model else "",
            "owner": module.owner,
            "version": module.version,
            "status": module.status,
            "fallback_content": module.fallback_content,
            "algorithm_fields": module.algorithm_fields,
            "knowledge_tags": module.knowledge_tags,
        },
        "prompt": {key: getattr(prompt, key) for key in PROMPT_KEYS},
        "fields": [serialize_field(field) for field in module.fields],
    }


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_ITERATIONS).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def login_admin(session: Session, payload: dict) -> dict | None:
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    user = session.scalar(select(AdminUser).where(AdminUser.username == username))
    if user is None or user.status != "active" or not verify_password(password, user.password_hash):
        record_audit_event(
            session,
            event_type="admin_login_failed",
            actor=username or "unknown",
            target_type="admin_user",
            target_id=username,
            severity="warning",
            status="blocked",
            details={"username": username},
        )
        return None

    token = generate_admin_token()
    expires_at = utc_now() + timedelta(days=ADMIN_SESSION_DAYS)
    admin_session = AdminSession(
        user_id=user.id,
        token_hash=hash_token(token),
        status=AdminSessionStatus.active.value,
        expires_at=expires_at,
    )
    user.last_login_at = utc_now()
    session.add(admin_session)
    session.commit()
    session.refresh(user)
    session.refresh(admin_session)
    record_audit_event(
        session,
        event_type="admin_login_success",
        actor=user.username,
        target_type="admin_user",
        target_id=str(user.id),
        severity="info",
        details={"role": user.role},
    )
    return {
        "token": token,
        "expires_at": admin_session.expires_at.isoformat(),
        "user": serialize_admin_user(user),
    }


def authenticate_admin_token(session: Session, token: str) -> AdminUser | None:
    if not token:
        return None
    admin_session = session.scalar(select(AdminSession).where(AdminSession.token_hash == hash_token(token)))
    if admin_session is None or admin_session.status != AdminSessionStatus.active.value:
        return None
    if is_expired(admin_session.expires_at):
        admin_session.status = AdminSessionStatus.revoked.value
        admin_session.revoked_at = utc_now()
        session.commit()
        return None
    user = session.get(AdminUser, admin_session.user_id)
    if user is None or user.status != "active":
        return None
    return user


def revoke_admin_token(session: Session, token: str) -> bool:
    if not token:
        return False
    admin_session = session.scalar(select(AdminSession).where(AdminSession.token_hash == hash_token(token)))
    if admin_session is None:
        return False
    admin_session.status = AdminSessionStatus.revoked.value
    admin_session.revoked_at = utc_now()
    session.commit()
    return True


def serialize_admin_user(user: AdminUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def generate_admin_token() -> str:
    return f"adm_{secrets.token_urlsafe(32)}"


def is_expired(value) -> bool:
    now = utc_now()
    if getattr(value, "tzinfo", None) is None:
        now = now.replace(tzinfo=None)
    return value <= now


def create_app_api_key(session: Session, payload: dict) -> dict:
    token = generate_app_token()
    key = AppApiKey(
        name=(payload.get("name") or "未命名 App Key").strip(),
        token_hash=hash_token(token),
        token_prefix=token[:12],
        scopes=payload.get("scopes") or ["app:render"],
        created_by=payload.get("operator") or "admin",
        status=AppKeyStatus.active.value,
    )
    session.add(key)
    session.commit()
    session.refresh(key)
    record_audit_event(
        session,
        event_type="app_key_created",
        actor=key.created_by,
        target_type="app_api_key",
        target_id=str(key.id),
        severity="info",
        details={"name": key.name, "scopes": key.scopes},
    )
    return {"token": token, "key": serialize_app_api_key(key)}


def list_app_api_keys(session: Session) -> list[dict]:
    keys = session.scalars(select(AppApiKey).order_by(AppApiKey.created_at.desc(), AppApiKey.id.desc())).all()
    return [serialize_app_api_key(key) for key in keys]


def revoke_app_api_key(session: Session, key_id: int, payload: dict) -> dict | None:
    key = session.get(AppApiKey, key_id)
    if key is None:
        return None
    key.status = AppKeyStatus.revoked.value
    key.revoked_at = utc_now()
    session.commit()
    session.refresh(key)
    record_audit_event(
        session,
        event_type="app_key_revoked",
        actor=payload.get("operator") or "admin",
        target_type="app_api_key",
        target_id=str(key.id),
        severity="warning",
        details={"name": key.name},
    )
    return serialize_app_api_key(key)


def authenticate_app_token(session: Session, token: str, default_token: str) -> dict | None:
    if token and token == default_token:
        return {"key_id": None, "name": "Default Dev Token", "source": "settings", "scopes": ["app:render"]}
    if not token:
        return None
    key = session.scalar(select(AppApiKey).where(AppApiKey.token_hash == hash_token(token)))
    if key is None or key.status != AppKeyStatus.active.value:
        return None
    key.last_used_at = utc_now()
    session.commit()
    return {"key_id": key.id, "name": key.name, "source": "database", "scopes": key.scopes}


def serialize_app_api_key(key: AppApiKey) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "token_prefix": key.token_prefix,
        "status": key.status,
        "scopes": key.scopes,
        "created_by": key.created_by,
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


def generate_app_token() -> str:
    return f"nexa_{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def record_audit_event(
    session: Session,
    event_type: str,
    actor: str = "system",
    target_type: str = "",
    target_id: str = "",
    severity: str = "info",
    status: str = "ok",
    details: dict | None = None,
) -> dict:
    event = AuditEvent(
        event_type=event_type,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        severity=severity,
        status=status,
        details=details or {},
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return serialize_audit_event(event)


def list_audit_events(session: Session, event_type: str | None = None, limit: int = 50) -> list[dict]:
    statement = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    if event_type:
        statement = select(AuditEvent).where(AuditEvent.event_type == event_type).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    events = session.scalars(statement).all()
    return [serialize_audit_event(event) for event in events]


def serialize_audit_event(event: AuditEvent) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "actor": event.actor,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "severity": event.severity,
        "status": event.status,
        "details": event.details,
        "created_at": event.created_at.isoformat(),
    }


def security_status(session: Session, default_token: str) -> dict:
    active_keys = session.scalar(select(func.count(AppApiKey.id)).where(AppApiKey.status == AppKeyStatus.active.value)) or 0
    revoked_keys = session.scalar(select(func.count(AppApiKey.id)).where(AppApiKey.status == AppKeyStatus.revoked.value)) or 0
    audit_count = session.scalar(select(func.count(AuditEvent.id))) or 0
    warning_count = session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.severity == "warning")) or 0
    failed_auth_count = session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.event_type == "app_auth_failed")) or 0
    admin_count = session.scalar(select(func.count(AdminUser.id))) or 0
    active_admin_sessions = session.scalar(
        select(func.count(AdminSession.id)).where(AdminSession.status == AdminSessionStatus.active.value)
    ) or 0
    return {
        "token_policy": {
            "using_default_dev_token": default_token == "dev-app-token",
            "managed_keys_enabled": True,
            "default_token_prefix": default_token[:4] + "***" if default_token else "",
        },
        "admin_auth": {
            "users": admin_count,
            "active_sessions": active_admin_sessions,
        },
        "app_keys": {
            "active": active_keys,
            "revoked": revoked_keys,
        },
        "audit_events": {
            "total": audit_count,
            "warnings": warning_count,
            "failed_auth": failed_auth_count,
        },
        "recent_events": list_audit_events(session, limit=8),
    }


def estimate_cost_cents(input_tokens: int, output_tokens: int) -> int:
    return int((input_tokens * 0.000075 + output_tokens * 0.00045) * 100)


def metrics(session: Session) -> dict:
    module_count = session.scalar(select(func.count(Module.id))) or 0
    field_count = session.scalar(select(func.count(FieldContract.id))) or 0
    call_count = session.scalar(select(func.count(CallTrace.id))) or 0
    fallback_count = session.scalar(select(func.count(CallTrace.id)).where(CallTrace.fallback_triggered.is_(True))) or 0
    return {
        "modules": module_count,
        "field_contracts": field_count,
        "call_traces": call_count,
        "fallback_triggers": fallback_count,
    }
