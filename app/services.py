from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import CallTrace, FieldContract, KnowledgeChunk, KnowledgeSource, ModelConfig, Module, Page, PromptTemplate


PROMPT_KEYS = [
    "shared_prefix",
    "module_rules",
    "algorithm_data_template",
    "user_preferences_template",
    "final_request_template",
]

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
        "issues": [
            {
                "id": issue.id,
                "title": issue.title,
                "issue_type": issue.issue_type,
                "owner": issue.owner,
                "status": issue.status,
                "created_at": issue.created_at.isoformat(),
            }
            for issue in module.issues
        ],
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

    prompt = module.prompt or PromptTemplate(module_id=module.id)
    model_name = module.model.display_name if module.model else "未配置"
    if payload.get("model_id"):
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
    summary = f"{module.name}测试输出：已根据 {payload.get('test_user', '测试用户')} 和 {payload.get('date', '未指定日期')} 生成内容。"
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
    input_tokens = max(1, len(model_request) // 4)
    output_tokens = max(1, len(str(raw_response)) // 4)
    trace = CallTrace(
        module_id=module.id,
        request_type="test",
        input_payload=payload,
        model_request=model_request,
        model_raw_response=str(raw_response),
        final_json=final_json,
        status="ok",
        fallback_triggered=False,
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


def list_call_traces(session: Session, limit: int = 20) -> list[dict]:
    traces = session.scalars(select(CallTrace).order_by(CallTrace.created_at.desc()).limit(limit)).all()
    return [serialize_call(trace) for trace in traces]


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
