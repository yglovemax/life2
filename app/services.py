from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import CallTrace, FieldContract, ModelConfig, Module, Page, PromptTemplate


PROMPT_KEYS = [
    "shared_prefix",
    "module_rules",
    "algorithm_data_template",
    "user_preferences_template",
    "final_request_template",
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
    input_payload = payload.get("input_payload") or {}
    model_request = "\n\n".join(
        [
            prompt.shared_prefix,
            prompt.module_rules,
            f"算法数据: {input_payload}",
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
        model_name=module.model.display_name if module.model else "未配置",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_cents=estimate_cost_cents(input_tokens, output_tokens),
    )
    session.add(trace)
    session.commit()
    session.refresh(trace)
    return serialize_call(trace)


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
