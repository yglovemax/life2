import base64
import binascii
import hashlib
import hmac
import json
import secrets
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.settings import get_settings
from app.platform.object_storage import safe_object_key
from app.platform.runtime import get_object_storage, get_task_queue
from app.platform.tasks import TaskEnvelope
from app.training.ai import (
    TRAINING_OUTPUT_SCHEMA,
    TRAINING_SYSTEM_PROMPT,
    build_training_prompt,
    normalize_training_chunks,
    parse_training_response,
)
from app.training.documents import entries_to_markdown, parse_training_document, safe_upload_filename
from app.training.github_import import fetch_github_training_files
from app.models import (
    AdminSession,
    AdminSessionStatus,
    AdminUser,
    AppApiKey,
    AppUser,
    AppKeyStatus,
    AuditEvent,
    BirthProfile,
    CallTrace,
    ChatMessage,
    ChatSession,
    FieldContract,
    Issue,
    IssueStatus,
    KnowledgeChunk,
    KnowledgeSource,
    MemoryItem,
    ModelConfig,
    ModelProviderKey,
    ModelProviderKeyStatus,
    Module,
    ModuleStatus,
    ModuleVersion,
    OutputPolicy,
    Page,
    PromptTemplate,
    TrainingDraftChunk,
    TrainingRun,
    UserMemorySummary,
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
TRAINING_QUALITY_RULES = [
    {
        "code": "absolute_claim",
        "severity": "blocker",
        "message": "避免绝对化、宿命论或确定性承诺。",
        "terms": ["一定会", "必然", "注定", "保证", "百分百", "绝对会", "肯定会"],
    },
    {
        "code": "medical_advice",
        "severity": "blocker",
        "message": "避免医疗、诊断、治疗或用药建议。",
        "terms": ["治疗", "治愈", "诊断", "用药", "处方"],
    },
    {
        "code": "legal_advice",
        "severity": "blocker",
        "message": "避免法律结论或诉讼承诺。",
        "terms": ["法律建议", "必赢官司", "诉讼必赢"],
    },
    {
        "code": "investment_advice",
        "severity": "blocker",
        "message": "避免投资收益、买卖建议或稳赚承诺。",
        "terms": ["投资收益", "稳赚", "买入", "卖出", "暴富"],
    },
]
QUALITY_NEGATION_PREFIXES = ["不要", "避免", "不能", "不可", "不应", "不是", "不做", "不替代"]

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
    return [serialize_model_config(model) for model in models]


def serialize_model_config(model: ModelConfig | None) -> dict | None:
    if model is None:
        return None
    return {
        "id": model.id,
        "provider": model.provider,
        "name": model.name,
        "display_name": model.display_name,
        "quality_tier": model.quality_tier,
        "input_cost_per_1m": model.input_cost_per_1m,
        "output_cost_per_1m": model.output_cost_per_1m,
        "is_active": model.is_active,
    }


def list_test_users() -> list[dict]:
    return DEMO_TEST_USERS


def create_knowledge_source(session: Session, payload: dict) -> dict:
    title = (payload.get("title") or "未命名资料").strip()
    content = payload.get("content") or ""
    tags = normalize_tags(payload.get("tags") or [])
    duplicate = find_duplicate_knowledge_source(session, content)
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
        chunk_model = KnowledgeChunk(
            source_id=source.id,
            title=chunk["title"],
            content=chunk["content"],
            tags=tags,
            chunk_index=index,
        )
        apply_text_embedding(chunk_model, f"{chunk_model.title}\n{chunk_model.content}")
        session.add(chunk_model)
        session.flush()
        sync_pgvector_embedding(session, "knowledge_chunks", chunk_model.id, chunk_model.embedding_payload)
    source.chunk_count = len(chunks)
    session.commit()
    session.refresh(source)
    return serialize_source(source, duplicate=duplicate)


def update_knowledge_source_status(session: Session, source_id: int, status: str) -> dict | None:
    if status not in {"active", "archived"}:
        raise ValueError("资料状态只能是 active 或 archived。")
    source = session.get(KnowledgeSource, source_id)
    if source is None:
        return None
    source.status = status
    session.commit()
    session.refresh(source)
    return serialize_source(source)


def delete_knowledge_source(session: Session, source_id: int) -> dict | None:
    source = session.get(KnowledgeSource, source_id)
    if source is None:
        return None
    if knowledge_source_is_referenced(session, source.id):
        raise ValueError("训练资料已被训练运行引用，请先归档，避免破坏版本记录。")
    session.delete(source)
    session.commit()
    return {"deleted": True, "source_id": source_id}


def knowledge_source_is_referenced(session: Session, source_id: int) -> bool:
    referenced_run_id = session.scalar(
        select(TrainingRun.id)
        .where((TrainingRun.source_id == source_id) | (TrainingRun.published_source_id == source_id))
        .limit(1)
    )
    return bool(referenced_run_id)


def merge_knowledge_source(session: Session, source_id: int, payload: dict) -> dict | None:
    source = session.get(KnowledgeSource, source_id)
    if source is None:
        return None
    target_id = nullable_int(payload.get("target_source_id"))
    if target_id is None:
        raise ValueError("请提供 target_source_id。")
    if target_id == source.id:
        raise ValueError("不能把资料合并到自己。")
    target = session.get(KnowledgeSource, target_id)
    if target is None:
        raise ValueError("目标资料不存在。")

    source_fingerprint = knowledge_source_fingerprint(source.content)
    target_fingerprint = knowledge_source_fingerprint(target.content)
    if not payload.get("force") and (not source_fingerprint or source_fingerprint != target_fingerprint):
        raise ValueError("只有内容完全重复的资料可以直接合并。")

    target.tags = merge_tags(target.tags or [], source.tags or [])
    source.status = "archived"
    session.commit()
    session.refresh(source)
    session.refresh(target)

    operator = str(payload.get("operator") or "admin").strip() or "admin"
    audit = record_audit_event(
        session,
        event_type="knowledge_source_merged",
        actor=operator,
        target_type="knowledge_source",
        target_id=str(source.id),
        severity="info",
        status="archived",
        details={
            "source_id": source.id,
            "target_source_id": target.id,
            "fingerprint": source_fingerprint,
            "source_title": source.title,
            "target_title": target.title,
        },
    )
    return {
        "merged": True,
        "source": serialize_source(source),
        "target": serialize_source(target),
        "audit_event": audit,
    }


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


def upload_knowledge_files(session: Session, payload: dict, source_prefix: str = "uploaded") -> dict:
    files = payload.get("files") or []
    if not files:
        raise ValueError("请至少选择一个训练资料文件。")

    settings = get_settings()
    storage = get_object_storage()
    base_tags = normalize_tags(payload.get("tags") or [])
    sources: list[dict] = []

    for index, file_payload in enumerate(files, start=1):
        filename = safe_upload_filename(file_payload.get("filename") or f"upload-{index}.txt")
        content = decode_upload_content(file_payload)
        if len(content) > settings.max_upload_file_bytes:
            raise ValueError(f"{filename} 超过单文件大小限制。")

        object_key = safe_object_key("knowledge/uploads", filename, f"upload_{uuid4().hex[:12]}")
        stored = storage.put_bytes(object_key, content, file_payload.get("content_type") or "application/octet-stream")
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        try:
            entries = parse_training_document(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)
        if not entries:
            raise ValueError(f"{filename} 没有解析出有效内容。")

        content_markdown = entries_to_markdown(entries)
        tags = merge_tags(base_tags, ["上传资料"] if source_prefix == "uploaded" else ["GitHub"])
        source = create_knowledge_source(
            session,
            {
                "title": file_payload.get("title") or Path(filename).stem,
                "source_type": source_type_for_upload(filename, source_prefix),
                "content": content_markdown,
                "tags": tags,
            },
        )
        source["object_key"] = stored.key
        source["entry_count"] = len(entries)
        sources.append(source)

    return {
        "uploaded": len(sources),
        "chunks_created": sum(source["chunk_count"] for source in sources),
        "sources": sources,
    }


def import_github_knowledge_sources(session: Session, payload: dict) -> dict:
    url = (payload.get("url") or "").strip()
    if not url:
        raise ValueError("请输入 GitHub 仓库、文件或文件夹链接。")
    github_files = fetch_github_training_files(url)
    files = [
        {
            "filename": file["filename"],
            "content": file["content"],
            "content_type": file.get("content_type") or "application/octet-stream",
            "metadata": file.get("metadata") or {},
        }
        for file in github_files
    ]
    return upload_knowledge_files(session, {**payload, "files": files}, source_prefix="github")


def decode_upload_content(file_payload: dict) -> bytes:
    if "content_base64" in file_payload:
        try:
            return base64.b64decode(str(file_payload.get("content_base64") or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("上传文件内容不是合法 base64。") from exc
    content = file_payload.get("content")
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raise ValueError("上传文件缺少内容。")


def source_type_for_upload(filename: str, source_prefix: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".") or "text"
    suffix = {"markdown": "md", "yml": "yaml"}.get(suffix, suffix)
    return f"{source_prefix}_{suffix}"


def merge_tags(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for tag in normalize_tags(group):
            if tag in seen:
                continue
            seen.add(tag)
            merged.append(tag)
    return merged


def create_training_run(session: Session, payload: dict) -> dict:
    source, entries, source_title, source_tags = resolve_training_entries(session, payload)
    prompt = build_training_prompt(source_title, entries)
    run_mode = "queued" if str(payload.get("run_mode") or "").strip().lower() == "queued" else "sync"
    run = TrainingRun(
        source_id=source.id if source else None,
        title=(payload.get("title") or source_title or "AI 训练运行").strip(),
        run_mode=run_mode,
        status="queued" if run_mode == "queued" else "running",
        task_id="",
        prompt=prompt,
        request_payload=normalize_training_run_payload(payload, source_id=source.id if source else None, source_title=source_title),
        created_by=payload.get("operator") or "admin",
    )
    session.add(run)
    session.flush()

    if run_mode == "queued":
        task = TaskEnvelope(task_type="training.run", payload={"run_id": run.id})
        run.task_id = get_task_queue().enqueue(task)
        session.commit()
        run = get_training_run_model(session, run.id)
        return serialize_training_run(run)

    return execute_training_run_record(session, run.id, payload=payload, source=source, entries=entries, source_title=source_title, source_tags=source_tags)


def normalize_training_run_payload(payload: dict, source_id: int | None, source_title: str) -> dict:
    clean = dict(payload)
    clean["run_mode"] = "queued" if str(payload.get("run_mode") or "").strip().lower() == "queued" else "sync"
    if source_id is not None:
        clean["source_id"] = source_id
    if not clean.get("title"):
        clean["title"] = source_title or "AI 训练运行"
    return clean


def execute_training_run_record(
    session: Session,
    run_id: int,
    payload: dict | None = None,
    source: KnowledgeSource | None = None,
    entries: list[dict] | None = None,
    source_title: str = "",
    source_tags: list[str] | None = None,
) -> dict | None:
    run = get_training_run_model(session, run_id)
    if run is None:
        return None
    payload = payload or (run.request_payload or {})
    if source is None or entries is None:
        source, entries, source_title, source_tags = resolve_training_entries(session, payload)
    source_tags = source_tags or []
    run.status = "running"
    session.commit()

    raw_response_text = ""
    parsed: dict = {}
    normalized_chunks: list[dict] = []
    error = ""

    try:
        if "simulate_model_response" in payload:
            raw_response_text = coerce_raw_model_response(payload.get("simulate_model_response"))
        elif should_call_live_model(payload):
            provider_result = call_training_model_provider(prompt, payload)
            raw_response_text = provider_result.get("raw_text") or ""
            if not provider_result.get("ok"):
                raise ValueError(provider_result.get("error") or provider_result.get("fallback_reason") or "模型调用失败")
        else:
            raw_response_text = build_mock_training_response(source_title, entries, source_tags)
        parsed = parse_training_response(raw_response_text)
        normalized_chunks = normalize_training_chunks(parsed)
        if not normalized_chunks:
            raise ValueError("模型输出没有可用知识片段")
    except ValueError as exc:
        error = str(exc)
        run.status = "failed"
        run.error = error
        run.raw_response = raw_response_text
        run.parsed_response = parsed
        run.draft_count = 0
        run.completed_at = utc_now()
        session.commit()
        session.refresh(run)
        return serialize_training_run(run)

    run.status = "completed"
    run.raw_response = raw_response_text
    run.parsed_response = parsed
    run.draft_count = len(normalized_chunks)
    run.completed_at = utc_now()
    merged_source_tags = merge_tags(source_tags, normalize_tags(payload.get("tags") or []))
    for index, chunk in enumerate(normalized_chunks, start=1):
        session.add(
            TrainingDraftChunk(
                run_id=run.id,
                title=chunk["title"],
                content=chunk["content"],
                domain=chunk["domain"],
                tags=merge_tags(chunk["tags"], merged_source_tags),
                confidence_x100=max(0, min(int(round(float(chunk.get("confidence") or 0) * 100)), 100)),
                status="draft",
                chunk_index=index,
            )
        )
    session.commit()
    run = get_training_run_model(session, run.id)
    return serialize_training_run(run)


def execute_training_run_job(session: Session, run_id: int) -> dict | None:
    run = get_training_run_model(session, run_id)
    if run is None:
        return None
    if run.status == "canceled":
        return serialize_training_run(run)
    return execute_training_run_record(session, run_id)


def retry_training_run(session: Session, run_id: int, payload: dict) -> dict | None:
    run = get_training_run_model(session, run_id)
    if run is None:
        return None
    if run.status in {"queued", "running"}:
        raise ValueError("训练运行仍在处理中，暂时不能重试。")

    merged_payload = dict(run.request_payload or {})
    merged_payload.update(payload or {})
    source, entries, source_title, source_tags = resolve_training_entries(session, merged_payload)
    run_mode = "queued" if str(merged_payload.get("run_mode") or "").strip().lower() == "queued" else "sync"

    for chunk in list(run.draft_chunks):
        session.delete(chunk)

    run.title = (merged_payload.get("title") or source_title or run.title).strip()
    run.run_mode = run_mode
    run.status = "queued" if run_mode == "queued" else "running"
    run.task_id = ""
    run.request_payload = normalize_training_run_payload(merged_payload, source_id=source.id if source else None, source_title=source_title)
    run.raw_response = ""
    run.parsed_response = {}
    run.error = ""
    run.draft_count = 0
    run.published_source_id = None
    run.completed_at = None
    session.flush()

    if run_mode == "queued":
        task = TaskEnvelope(task_type="training.run", payload={"run_id": run.id})
        run.task_id = get_task_queue().enqueue(task)
        session.commit()
        run = get_training_run_model(session, run.id)
        return serialize_training_run(run)

    return execute_training_run_record(session, run.id, payload=merged_payload, source=source, entries=entries, source_title=source_title, source_tags=source_tags)


def cancel_training_run(session: Session, run_id: int) -> dict | None:
    run = get_training_run_model(session, run_id)
    if run is None:
        return None
    if run.status != "queued":
        raise ValueError("只有排队中的训练运行可以取消。")
    run.status = "canceled"
    run.task_id = ""
    run.completed_at = utc_now()
    session.commit()
    run = get_training_run_model(session, run.id)
    return serialize_training_run(run)


def resolve_training_entries(session: Session, payload: dict) -> tuple[KnowledgeSource | None, list[dict], str, list[str]]:
    source_id = nullable_int(payload.get("source_id"))
    if source_id is not None:
        source = session.get(KnowledgeSource, source_id)
        if source is None:
            raise ValueError("训练资料来源不存在。")
        chunks = list_knowledge_chunks(session, source_id=source.id)
        entries = [
            {
                "source_id": source.id,
                "chunk_id": chunk["id"],
                "title": chunk["title"],
                "body": chunk["content"],
                "tags": chunk["tags"],
            }
            for chunk in chunks
        ]
        if not entries and source.content:
            entries = [{"source_id": source.id, "title": source.title, "body": source.content, "tags": source.tags}]
        return source, entries, source.title, source.tags or []

    content = payload.get("content") or ""
    if not str(content).strip():
        raise ValueError("请提供 source_id 或 content。")
    title = (payload.get("title") or "临时训练资料").strip()
    entries = [
        {"source_id": "", "chunk_id": index, "title": chunk["title"], "body": chunk["content"], "tags": normalize_tags(payload.get("tags") or [])}
        for index, chunk in enumerate(chunk_markdown(title, str(content)), start=1)
    ]
    return None, entries, title, normalize_tags(payload.get("tags") or [])


def build_mock_training_response(source_title: str, entries: list[dict], source_tags: list[str]) -> str:
    chunks = []
    for entry in entries[:3]:
        title = entry.get("title") or source_title
        body = compact_text(entry.get("body") or entry.get("content") or "", 180)
        if not body:
            continue
        chunks.append(
            {
                "title": f"{title} 训练规则",
                "body": body,
                "domain": "astrology",
                "tags": merge_tags(source_tags, entry.get("tags") or [], ["mock_training"]),
                "rule_type": "mock_extraction",
                "use_when": "用于本地开发和接口联调",
                "avoid_when": "不要把 mock 结果当成最终训练结论",
                "examples": [],
                "confidence": 0.6,
            }
        )
    return json.dumps({"chunks": chunks}, ensure_ascii=False)


def compact_text(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip("，。；、 ") + "..."


def call_training_model_provider(prompt: str, payload: dict) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        return {"ok": False, "fallback_reason": "provider_key_missing", "error": "NEXA_OPENAI_API_KEY is not configured", "raw_text": ""}

    endpoint = settings.openai_base_url.rstrip("/") + "/responses"
    model_name = payload.get("model_name") or "gpt-5.4-mini"
    request_body = {
        "model": model_name,
        "input": [
            {"role": "system", "content": TRAINING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "store": False,
        "max_output_tokens": int(payload.get("max_output_tokens") or 1200),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "nexa_training_extraction",
                "strict": False,
                "schema": TRAINING_OUTPUT_SCHEMA,
            }
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.model_request_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "fallback_reason": "model_provider_error", "error": detail, "raw_text": detail}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"ok": False, "fallback_reason": "model_provider_error", "error": str(error), "raw_text": str(error)}

    raw_text = extract_openai_output_text(response_payload)
    return {
        "ok": bool(raw_text),
        "fallback_reason": "" if raw_text else "empty_model_response",
        "error": "" if raw_text else "OpenAI response did not include output text",
        "raw_text": raw_text,
    }


def list_training_runs(session: Session, limit: int = 30) -> list[dict]:
    runs = session.scalars(
        select(TrainingRun)
        .options(selectinload(TrainingRun.draft_chunks), joinedload(TrainingRun.source), joinedload(TrainingRun.published_source))
        .order_by(TrainingRun.created_at.desc(), TrainingRun.id.desc())
        .limit(limit)
    ).all()
    return [serialize_training_run(run, include_raw=False) for run in runs]


def training_queue_status(session: Session) -> dict:
    queue = get_task_queue()
    backend = get_settings().task_queue_backend.strip().lower() or "memory"
    runs = session.scalars(select(TrainingRun).order_by(TrainingRun.created_at.desc(), TrainingRun.id.desc())).all()
    counts = {
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "published": 0,
        "canceled": 0,
    }
    queued_run_ids: list[int] = []
    for run in runs:
        if run.status in counts:
            counts[run.status] += 1
        if run.status == "queued":
            queued_run_ids.append(run.id)
    return {
        "backend": backend,
        "pending_tasks": queue.size(),
        "runs": counts,
        "queued_run_ids": queued_run_ids,
    }


def get_training_run(session: Session, run_id: int) -> dict | None:
    run = get_training_run_model(session, run_id)
    if run is None:
        return None
    data = serialize_training_run(run)
    data["quality_events"] = list_training_quality_events(session, run.id)
    return data


def get_training_run_model(session: Session, run_id: int) -> TrainingRun | None:
    return session.scalar(
        select(TrainingRun)
        .where(TrainingRun.id == run_id)
        .options(selectinload(TrainingRun.draft_chunks), joinedload(TrainingRun.source), joinedload(TrainingRun.published_source))
    )


def build_training_quality_report(session: Session, run_id: int, override: bool = False) -> dict | None:
    run = get_training_run_model(session, run_id)
    if run is None:
        return None
    draft_chunks = [chunk for chunk in sorted(run.draft_chunks, key=lambda item: item.chunk_index) if chunk.status == "draft"]
    return build_training_quality_report_for_chunks(run, draft_chunks, override=override)


def build_training_quality_report_for_chunks(run: TrainingRun, draft_chunks: list[TrainingDraftChunk], override: bool = False) -> dict:
    issues: list[dict] = []
    total_chars = 0
    confidences: list[float] = []

    if not draft_chunks:
        issues.append(
            {
                "code": "no_draft_chunks",
                "severity": "blocker",
                "message": "没有可发布的训练草稿。",
                "chunk_id": None,
                "chunk_title": "",
                "matches": [],
            }
        )

    for chunk in draft_chunks:
        text = f"{chunk.title}\n{chunk.content}".strip()
        total_chars += len(text)
        confidence = max(0.0, min((chunk.confidence_x100 or 0) / 100, 1.0))
        confidences.append(confidence)
        if len(chunk.content.strip()) < 30:
            issues.append(training_quality_issue("short_content", "warning", "知识片段正文偏短，建议补充适用场景和边界。", chunk, []))
        if confidence < 0.5:
            issues.append(training_quality_issue("low_confidence", "blocker", "模型抽取置信度过低，不建议直接发布。", chunk, [f"{confidence:.2f}"]))
        elif confidence < 0.7:
            issues.append(training_quality_issue("low_confidence", "warning", "模型抽取置信度偏低，建议人工复核。", chunk, [f"{confidence:.2f}"]))

        for rule in TRAINING_QUALITY_RULES:
            matches = find_quality_terms(text, rule["terms"])
            if matches:
                issues.append(training_quality_issue(rule["code"], rule["severity"], rule["message"], chunk, matches))

    blocker_count = sum(1 for issue in issues if issue["severity"] == "blocker")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "blocked" if blocker_count else "warning" if warning_count else "passed"
    can_publish = blocker_count == 0 or override
    return {
        "run_id": run.id,
        "run_status": run.status,
        "status": status,
        "can_publish": can_publish,
        "override": bool(override),
        "metrics": {
            "draft_count": len(draft_chunks),
            "total_chars": total_chars,
            "average_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0,
            "min_confidence": round(min(confidences), 4) if confidences else 0,
            "blocker_count": blocker_count,
            "warning_count": warning_count,
        },
        "issues": issues,
    }


def training_quality_issue(code: str, severity: str, message: str, chunk: TrainingDraftChunk, matches: list[str]) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "chunk_id": chunk.id,
        "chunk_title": chunk.title,
        "matches": matches,
    }


def find_quality_terms(text: str, terms: list[str]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            if not quality_term_is_negated(text, index):
                matches.append(term)
                break
            start = index + len(term)
    return matches


def quality_term_is_negated(text: str, index: int) -> bool:
    prefix = text[max(0, index - 4) : index]
    return any(marker in prefix for marker in QUALITY_NEGATION_PREFIXES)


def training_quality_failure_message(report: dict) -> str:
    blockers = [issue for issue in report.get("issues", []) if issue.get("severity") == "blocker"]
    codes = []
    for issue in blockers:
        code = issue.get("code") or "unknown"
        if code not in codes:
            codes.append(code)
    return "、".join(codes[:4]) or "存在阻断问题"


def record_training_quality_event(session: Session, run: TrainingRun, report: dict, event_type: str, payload: dict) -> dict:
    operator = (payload.get("operator") or "system").strip() if isinstance(payload.get("operator"), str) else "system"
    severity = "warning" if event_type in {"training_quality_blocked", "training_quality_override"} else "info"
    status = {
        "training_quality_blocked": "blocked",
        "training_quality_override": "override",
        "training_quality_passed": "ok",
    }.get(event_type, "ok")
    return record_audit_event(
        session,
        event_type=event_type,
        actor=operator,
        target_type="training_run",
        target_id=str(run.id),
        severity=severity,
        status=status,
        details={
            "run_id": run.id,
            "source_id": run.source_id,
            "published_source_id": run.published_source_id,
            "quality_report": report,
        },
    )


def list_training_quality_events(session: Session, run_id: int, limit: int = 20) -> list[dict]:
    events = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.target_type == "training_run",
            AuditEvent.target_id == str(run_id),
            AuditEvent.event_type.in_(["training_quality_blocked", "training_quality_override", "training_quality_passed"]),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    ).all()
    return [serialize_audit_event(event) for event in events]


def publish_training_run(session: Session, run_id: int, payload: dict) -> dict | None:
    run = get_training_run_model(session, run_id)
    if run is None:
        return None
    draft_chunks = [chunk for chunk in sorted(run.draft_chunks, key=lambda item: item.chunk_index) if chunk.status == "draft"]
    if not draft_chunks:
        raise ValueError("没有可发布的训练草稿。")
    override_quality_gate = bool(payload.get("override_quality_gate"))
    quality_report = build_training_quality_report_for_chunks(run, draft_chunks, override=override_quality_gate)
    if not quality_report["can_publish"]:
        record_training_quality_event(session, run, quality_report, "training_quality_blocked", payload)
        raise ValueError(f"训练质检未通过：{training_quality_failure_message(quality_report)}")

    tags = merge_tags(
        normalize_tags(payload.get("tags") or []),
        ["ai_training"],
        [tag for chunk in draft_chunks for tag in (chunk.tags or [])],
    )
    content = "\n\n".join(f"# {chunk.title}\n{chunk.content}" for chunk in draft_chunks)
    source = KnowledgeSource(
        title=(payload.get("title") or f"AI 训练：{run.title}").strip(),
        source_type="ai_training",
        content=content,
        tags=tags,
        status="active",
    )
    session.add(source)
    session.flush()
    chunks = chunk_markdown(source.title, content)
    for index, chunk in enumerate(chunks, start=1):
        chunk_model = KnowledgeChunk(
            source_id=source.id,
            title=chunk["title"],
            content=chunk["content"],
            tags=tags,
            chunk_index=index,
        )
        apply_text_embedding(chunk_model, f"{chunk_model.title}\n{chunk_model.content}")
        session.add(chunk_model)
        session.flush()
        sync_pgvector_embedding(session, "knowledge_chunks", chunk_model.id, chunk_model.embedding_payload)
    source.chunk_count = len(chunks)
    for chunk in draft_chunks:
        chunk.status = "published"
    run.status = "published"
    run.published_source_id = source.id
    run.completed_at = utc_now()
    session.commit()
    run = get_training_run_model(session, run.id)
    event_type = "training_quality_override" if override_quality_gate and quality_report["status"] == "blocked" else "training_quality_passed"
    record_training_quality_event(session, run, quality_report, event_type, payload)
    result = serialize_training_run(run)
    result["published_source"] = serialize_source(source)
    result["quality_report"] = quality_report
    result["quality_events"] = list_training_quality_events(session, run.id)
    return result


def serialize_training_run(run: TrainingRun, include_raw: bool = True) -> dict:
    data = {
        "id": run.id,
        "source_id": run.source_id,
        "source_title": run.source.title if run.source else "",
        "published_source_id": run.published_source_id,
        "title": run.title,
        "run_mode": run.run_mode,
        "status": run.status,
        "task_id": run.task_id,
        "error": run.error,
        "draft_count": run.draft_count,
        "created_by": run.created_by,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "draft_chunks": [serialize_training_draft_chunk(chunk) for chunk in sorted(run.draft_chunks, key=lambda item: item.chunk_index)],
    }
    if include_raw:
        data["prompt"] = run.prompt
        data["raw_response"] = run.raw_response
        data["parsed_response"] = run.parsed_response or {}
    return data


def serialize_training_draft_chunk(chunk: TrainingDraftChunk) -> dict:
    return {
        "id": chunk.id,
        "run_id": chunk.run_id,
        "title": chunk.title,
        "content": chunk.content,
        "domain": chunk.domain,
        "tags": chunk.tags or [],
        "confidence": chunk.confidence_x100 / 100,
        "status": chunk.status,
        "chunk_index": chunk.chunk_index,
        "created_at": chunk.created_at.isoformat(),
    }


def list_knowledge_sources(session: Session) -> list[dict]:
    sources = session.scalars(select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc())).all()
    return [serialize_source(source) for source in sources]


def list_knowledge_duplicate_groups(session: Session) -> list[dict]:
    sources = session.scalars(select(KnowledgeSource).order_by(KnowledgeSource.created_at.asc(), KnowledgeSource.id.asc())).all()
    groups: dict[str, list[KnowledgeSource]] = {}
    for source in sources:
        fingerprint = knowledge_source_fingerprint(source.content)
        if not fingerprint:
            continue
        groups.setdefault(fingerprint, []).append(source)

    rows: list[dict] = []
    for fingerprint, group_sources in groups.items():
        if len(group_sources) < 2:
            continue
        active_sources = [source for source in group_sources if source.status == "active"]
        canonical = active_sources[0] if active_sources else group_sources[0]
        rows.append(
            {
                "fingerprint": fingerprint,
                "source_count": len(group_sources),
                "active_count": len(active_sources),
                "canonical_source": serialize_source(canonical),
                "sources": [serialize_source(source) for source in group_sources],
            }
        )
    rows.sort(key=lambda item: (item["active_count"], item["source_count"]), reverse=True)
    return rows


def list_knowledge_cleanup_recommendations(session: Session) -> dict:
    sources = session.scalars(select(KnowledgeSource).order_by(KnowledgeSource.created_at.asc(), KnowledgeSource.id.asc())).all()
    sources_by_id = {source.id: source for source in sources}
    items: list[dict] = []

    for group in list_knowledge_duplicate_groups(session):
        canonical_id = group["canonical_source"]["id"]
        canonical = sources_by_id.get(canonical_id)
        if canonical is None:
            continue
        for source_data in group["sources"]:
            source_id = source_data["id"]
            source = sources_by_id.get(source_id)
            if source is None or source.id == canonical_id or source.status != "active":
                continue
            items.append(
                {
                    "id": f"merge_duplicate_source:{source.id}:{canonical.id}",
                    "action": "merge_duplicate_source",
                    "severity": "medium",
                    "source_id": source.id,
                    "target_source_id": canonical.id,
                    "title": "合并重复知识源",
                    "reason": "内容指纹完全一致，建议把重复源合并到主源并归档重复源。",
                    "method": "POST",
                    "endpoint": f"/api/knowledge-sources/{source.id}/merge",
                    "payload": {"target_source_id": canonical.id},
                    "safe_to_run": True,
                    "source": serialize_source(source),
                    "target": serialize_source(canonical),
                }
            )

    for source in sources:
        if source.status != "archived":
            continue
        if knowledge_source_is_referenced(session, source.id):
            continue
        items.append(
            {
                "id": f"delete_archived_unused_source:{source.id}",
                "action": "delete_archived_unused_source",
                "severity": "low",
                "source_id": source.id,
                "target_source_id": None,
                "title": "删除已归档且未引用知识源",
                "reason": "资料已归档且没有训练运行引用，可以考虑硬删除以减少后台噪音。",
                "method": "DELETE",
                "endpoint": f"/api/knowledge-sources/{source.id}",
                "payload": {},
                "safe_to_run": True,
                "source": serialize_source(source),
                "target": None,
            }
        )

    severity_order = {"medium": 0, "low": 1}
    items.sort(key=lambda item: (severity_order.get(item["severity"], 9), item["action"], item["source_id"]))
    action_counts: dict[str, int] = {}
    for item in items:
        action_counts[item["action"]] = action_counts.get(item["action"], 0) + 1
    return {
        "summary": {
            "total": len(items),
            "by_action": action_counts,
        },
        "items": items,
    }


def execute_knowledge_cleanup_recommendations(session: Session, payload: dict) -> dict:
    requested_ids = [str(item).strip() for item in payload.get("recommendation_ids") or [] if str(item).strip()]
    operator = str(payload.get("operator") or "admin").strip() or "admin"
    recommendations = {item["id"]: item for item in list_knowledge_cleanup_recommendations(session)["items"]}
    rows: list[dict] = []

    for recommendation_id in requested_ids:
        recommendation = recommendations.get(recommendation_id)
        if recommendation is None:
            rows.append(
                {
                    "recommendation_id": recommendation_id,
                    "action": "",
                    "source_id": None,
                    "target_source_id": None,
                    "status": "failed",
                    "error": "清理建议不存在或已过期。",
                    "result": None,
                }
            )
            continue

        try:
            result = execute_knowledge_cleanup_recommendation(session, recommendation, operator)
            rows.append(
                {
                    "recommendation_id": recommendation_id,
                    "action": recommendation["action"],
                    "source_id": recommendation["source_id"],
                    "target_source_id": recommendation.get("target_source_id"),
                    "status": "completed",
                    "error": "",
                    "result": result,
                }
            )
        except ValueError as exc:
            rows.append(
                {
                    "recommendation_id": recommendation_id,
                    "action": recommendation["action"],
                    "source_id": recommendation["source_id"],
                    "target_source_id": recommendation.get("target_source_id"),
                    "status": "failed",
                    "error": str(exc),
                    "result": None,
                }
            )

    summary = {
        "requested": len(requested_ids),
        "completed": sum(1 for row in rows if row["status"] == "completed"),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
    }
    audit = record_audit_event(
        session,
        event_type="knowledge_cleanup_executed",
        actor=operator,
        target_type="knowledge_cleanup",
        target_id=f"cleanup_{uuid4().hex[:16]}",
        severity="info" if summary["failed"] == 0 else "warning",
        status="completed" if summary["failed"] == 0 else "partial",
        details={"summary": summary, "items": rows},
    )
    return {"summary": summary, "items": rows, "audit_event": audit}


def execute_knowledge_cleanup_recommendation(session: Session, recommendation: dict, operator: str) -> dict:
    action = recommendation.get("action")
    source_id = int(recommendation.get("source_id") or 0)
    if action == "merge_duplicate_source":
        return merge_knowledge_source(
            session,
            source_id,
            {"target_source_id": recommendation.get("target_source_id"), "operator": operator},
        ) or {}
    if action == "delete_archived_unused_source":
        return delete_knowledge_source(session, source_id) or {}
    raise ValueError("不支持的清理动作。")


def knowledge_source_fingerprint(content: str) -> str:
    clean = "\n".join(line.strip() for line in str(content or "").splitlines() if line.strip())
    if not clean:
        return ""
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def find_duplicate_knowledge_source(session: Session, content: str, exclude_id: int | None = None) -> KnowledgeSource | None:
    fingerprint = knowledge_source_fingerprint(content)
    if not fingerprint:
        return None
    sources = session.scalars(select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc(), KnowledgeSource.id.desc())).all()
    for source in sources:
        if exclude_id is not None and source.id == exclude_id:
            continue
        if knowledge_source_fingerprint(source.content) == fingerprint:
            return source
    return None


def duplicate_source_meta(source: KnowledgeSource | None) -> dict:
    if source is None:
        return {"is_duplicate": False, "source_id": None, "title": "", "status": ""}
    return {
        "is_duplicate": True,
        "source_id": source.id,
        "title": source.title,
        "status": source.status,
    }


def knowledge_taxonomy() -> list[dict]:
    return [
        {
            "system": "astrology",
            "label": "西洋占星",
            "dimensions": ["太阳星座", "月亮星座", "上升", "宫位", "相位", "元素", "模式", "主题"],
            "recommended_tags": ["占星", "本命", "日运", "关系", "事业", "情绪", "成长"],
        },
        {
            "system": "bazi",
            "label": "八字",
            "dimensions": ["四柱", "日主", "五行", "十神", "格局", "大运", "流年", "主题"],
            "recommended_tags": ["八字", "四柱", "日主", "十神", "事业", "财运", "关系", "流年"],
        },
    ]


def list_knowledge_chunks(session: Session, tag: str | None = None, source_id: int | None = None) -> list[dict]:
    statement = select(KnowledgeChunk).options(joinedload(KnowledgeChunk.source)).order_by(KnowledgeChunk.created_at.desc())
    chunks = session.scalars(statement).all()
    if source_id is None:
        chunks = [chunk for chunk in chunks if chunk.source and chunk.source.status == "active"]
    rows = [serialize_chunk(chunk) for chunk in chunks]
    if source_id is not None:
        rows = [row for row in rows if row["source_id"] == source_id]
    if tag:
        rows = [row for row in rows if tag in row["tags"]]
    return rows


def search_knowledge_with_pgvector(session: Session, query_embedding: dict, tags: list[str], limit: int) -> list[dict] | None:
    if not is_postgres_session(session):
        return None
    literal = embedding_vector_literal(query_embedding)
    if not literal:
        return None
    fetch_limit = max(limit * 5, limit, 10)
    try:
        rows = (
            session.execute(
                text(
                    """
                    SELECT id, 1 - (embedding <=> CAST(:embedding AS vector)) AS semantic_score
                    FROM knowledge_chunks
                    WHERE embedding IS NOT NULL
                    AND EXISTS (
                        SELECT 1
                        FROM knowledge_sources
                        WHERE knowledge_sources.id = knowledge_chunks.source_id
                        AND knowledge_sources.status = 'active'
                    )
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                    """
                ),
                {"embedding": literal, "limit": fetch_limit},
            )
            .mappings()
            .all()
        )
    except Exception:
        return None
    if not rows:
        return []

    scores = {int(row["id"]): float(row.get("semantic_score") or 0.0) for row in rows}
    ordered_ids = [int(row["id"]) for row in rows]
    chunks = session.scalars(select(KnowledgeChunk).options(joinedload(KnowledgeChunk.source)).where(KnowledgeChunk.id.in_(ordered_ids))).all()
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    results: list[dict] = []
    for chunk_id in ordered_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        source = getattr(chunk, "source", None)
        if source is not None and source.status != "active":
            continue
        chunk_tags = chunk.tags or []
        if tags and not set(tags).intersection(set(chunk_tags)):
            continue
        row = serialize_chunk(chunk)
        row["semantic_score"] = round(scores.get(chunk_id, 0.0), 6)
        results.append(row)
        if len(results) >= limit:
            break
    return results


def search_knowledge(session: Session, payload: dict) -> list[dict]:
    query = (payload.get("query") or "").strip().lower()
    tags = normalize_tags(payload.get("tags") or [])
    limit = int(payload.get("limit") or 8)
    query_embedding = build_text_embedding_payload(query) if query else {}
    pgvector_results = search_knowledge_with_pgvector(session, query_embedding, tags, limit) if query_embedding else None
    if pgvector_results is not None:
        return pgvector_results

    chunks = session.scalars(select(KnowledgeChunk).options(joinedload(KnowledgeChunk.source)).order_by(KnowledgeChunk.created_at.desc())).all()
    scored: list[tuple[float, dict]] = []
    for chunk in chunks:
        if not chunk.source or chunk.source.status != "active":
            continue
        chunk_tags = chunk.tags or []
        if tags and not set(tags).intersection(set(chunk_tags)):
            continue
        haystack = f"{chunk.title}\n{chunk.content}".lower()
        lexical_score = 0
        if query and query in haystack:
            lexical_score += 5
        lexical_score += len(set(tags).intersection(set(chunk_tags)))
        if not query and lexical_score == 0 and tags:
            lexical_score = 1
        semantic_score = embedding_similarity(query_embedding, chunk.embedding_payload or {}) if query_embedding else 0.0
        if lexical_score > 0 or semantic_score > 0.05 or (not query and not tags):
            row = serialize_chunk(chunk)
            row["semantic_score"] = round(semantic_score, 6)
            scored.append((float(lexical_score) + semantic_score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]]


def create_embedding_rebuild_job(session: Session, payload: dict) -> dict:
    request = normalize_embedding_rebuild_payload(payload)
    if request["run_mode"] == "queued":
        task = TaskEnvelope(task_type="embedding.rebuild", payload=request)
        task_id = get_task_queue().enqueue(task)
        return embedding_rebuild_result(
            request,
            status="queued",
            task_id=task_id,
            knowledge_count=0,
            memory_count=0,
        )
    return execute_embedding_rebuild_job(session, request)


def execute_embedding_rebuild_job(session: Session, payload: dict) -> dict:
    request = normalize_embedding_rebuild_payload(payload)
    knowledge_count = 0
    memory_count = 0

    if request["target"] in {"all", "knowledge"}:
        knowledge_query = select(KnowledgeChunk).order_by(KnowledgeChunk.id)
        if request["source_id"] is not None:
            knowledge_query = knowledge_query.where(KnowledgeChunk.source_id == request["source_id"])
        knowledge_chunks = session.scalars(knowledge_query.limit(request["limit"])).all()
        for chunk in knowledge_chunks:
            if not should_rebuild_embedding(chunk, force=request["force"]):
                continue
            apply_text_embedding(chunk, f"{chunk.title}\n{chunk.content}")
            sync_pgvector_embedding(session, "knowledge_chunks", chunk.id, chunk.embedding_payload)
            knowledge_count += 1

    if request["target"] in {"all", "memory"}:
        memory_query = select(MemoryItem).order_by(MemoryItem.id)
        if request["user_id"] is not None:
            memory_query = memory_query.where(MemoryItem.user_id == request["user_id"])
        memory_items = session.scalars(memory_query.limit(request["limit"])).all()
        for item in memory_items:
            if not should_rebuild_embedding(item, force=request["force"]):
                continue
            apply_text_embedding(item, f"{item.memory_type}\n{item.content}")
            sync_pgvector_embedding(session, "memory_items", item.id, item.embedding_payload)
            memory_count += 1

    session.commit()
    return embedding_rebuild_result(
        request,
        status="completed",
        task_id=str(payload.get("task_id") or ""),
        knowledge_count=knowledge_count,
        memory_count=memory_count,
    )


def normalize_embedding_rebuild_payload(payload: dict) -> dict:
    target = str(payload.get("target") or "all").strip().lower()
    if target not in {"all", "knowledge", "memory"}:
        raise ValueError("embedding rebuild target must be all, knowledge, or memory")
    run_mode = "queued" if str(payload.get("run_mode") or "").strip().lower() == "queued" else "sync"
    return {
        "target": target,
        "run_mode": run_mode,
        "source_id": nullable_int(payload.get("source_id")),
        "user_id": nullable_int(payload.get("user_id")),
        "limit": clamp_int(payload.get("limit"), 1, 10000, 1000),
        "force": payload_bool(payload.get("force"), default=True),
    }


def should_rebuild_embedding(record, force: bool = True) -> bool:
    if force:
        return True
    payload = record.embedding_payload or {}
    settings = get_settings()
    return (
        not payload
        or record.embedding_model != settings.embedding_model
        or int(payload.get("dimensions") or 0) != settings.embedding_dimensions
        or str(payload.get("provider") or "").strip().lower() != settings.embedding_provider.strip().lower()
    )


def payload_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def embedding_rebuild_result(
    request: dict,
    status: str,
    task_id: str,
    knowledge_count: int,
    memory_count: int,
) -> dict:
    settings = get_settings()
    processed = knowledge_count + memory_count
    return {
        "status": status,
        "run_mode": request["run_mode"],
        "target": request["target"],
        "source_id": request["source_id"],
        "user_id": request["user_id"],
        "limit": request["limit"],
        "force": request["force"],
        "processed": processed,
        "knowledge_chunks": knowledge_count,
        "memory_items": memory_count,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "task_id": task_id,
    }


def retrieve_knowledge_hits(session: Session, tags: list, input_payload: dict, limit: int = 3) -> list[dict]:
    query_terms = knowledge_query_terms(input_payload)
    query = " ".join(str(term) for term in query_terms if term)
    hits = search_knowledge(session, {"query": query, "tags": tags, "limit": limit})
    if not hits and tags:
        hits = search_knowledge(session, {"query": "", "tags": tags, "limit": limit})
    return hits


def knowledge_query_terms(input_payload: dict) -> list[str]:
    bazi_profile = input_payload.get("bazi_profile") if isinstance(input_payload.get("bazi_profile"), dict) else {}
    pillars = input_payload.get("pillars") if isinstance(input_payload.get("pillars"), dict) else {}
    return [
        input_payload.get("sun_sign"),
        input_payload.get("moon_sign"),
        input_payload.get("rising_sign"),
        input_payload.get("topic"),
        input_payload.get("chart_system"),
        input_payload.get("system_type"),
        input_payload.get("day_master"),
        input_payload.get("year_pillar"),
        input_payload.get("month_pillar"),
        input_payload.get("day_pillar"),
        input_payload.get("hour_pillar"),
        bazi_profile.get("day_master"),
        bazi_profile.get("year_pillar"),
        bazi_profile.get("month_pillar"),
        bazi_profile.get("day_pillar"),
        bazi_profile.get("hour_pillar"),
        pillars.get("year"),
        pillars.get("month"),
        pillars.get("day"),
        pillars.get("hour"),
    ]


def serialize_source(source: KnowledgeSource, duplicate: KnowledgeSource | None = None) -> dict:
    return {
        "id": source.id,
        "title": source.title,
        "source_type": source.source_type,
        "status": source.status,
        "tags": source.tags,
        "chunk_count": source.chunk_count,
        "duplicate": duplicate_source_meta(duplicate),
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
        "embedding": serialize_embedding_meta(chunk),
        "semantic_score": 0,
        "created_at": chunk.created_at.isoformat(),
    }


def serialize_embedding_meta(record) -> dict:
    payload = record.embedding_payload or {}
    return {
        "status": "ready" if payload else "missing",
        "model": record.embedding_model or payload.get("model") or "",
        "hash": record.embedding_hash or payload.get("hash") or "",
        "dimensions": int(payload.get("dimensions") or get_settings().embedding_dimensions),
        "provider": payload.get("provider") or ("mock" if payload else ""),
    }


PGVECTOR_TABLES = {"knowledge_chunks", "memory_items"}


def embedding_vector_literal(payload: dict) -> str:
    vector = payload.get("vector") if isinstance(payload, dict) else None
    if not isinstance(vector, list) or not vector:
        return ""
    try:
        values = [format(float(value), ".12g") for value in vector]
    except (TypeError, ValueError):
        return ""
    return "[" + ",".join(values) + "]"


def is_postgres_session(session: Session) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def sync_pgvector_embedding(session: Session, table_name: str, record_id: int | None, payload: dict) -> bool:
    if table_name not in PGVECTOR_TABLES:
        raise ValueError("unsupported pgvector table")
    if not record_id or not is_postgres_session(session):
        return False
    literal = embedding_vector_literal(payload)
    if not literal:
        return False
    session.execute(
        text(f"UPDATE {table_name} SET embedding = CAST(:embedding AS vector) WHERE id = :id"),
        {"embedding": literal, "id": int(record_id)},
    )
    return True


def apply_text_embedding(record, text: str) -> None:
    payload = build_text_embedding_payload(text)
    record.embedding_payload = payload
    record.embedding_model = payload["model"]
    record.embedding_hash = payload["hash"]


def build_text_embedding_payload(text: str) -> dict:
    settings = get_settings()
    clean = " ".join(str(text or "").strip().lower().split())
    if settings.embedding_provider.strip().lower() == "openai":
        provider_payload = call_openai_embedding_provider(clean)
        if provider_payload.get("ok"):
            return provider_payload["payload"]
        mock_payload = build_mock_embedding_payload(clean)
        mock_payload["fallback_reason"] = provider_payload.get("fallback_reason") or "openai_embedding_error"
        mock_payload["provider_error"] = provider_payload.get("error") or ""
        return mock_payload
    return build_mock_embedding_payload(clean)


def build_mock_embedding_payload(clean: str) -> dict:
    settings = get_settings()
    features = embedding_features(clean)
    digest = hashlib.sha256(f"{settings.embedding_model}\n{clean}".encode("utf-8")).hexdigest()
    return {
        "status": "ready",
        "provider": "mock",
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "hash": digest,
        "features": features,
    }


def call_openai_embedding_provider(clean: str) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        return {"ok": False, "fallback_reason": "openai_api_key_missing", "error": "NEXA_OPENAI_API_KEY is not configured"}
    if not clean:
        return {"ok": False, "fallback_reason": "empty_embedding_input", "error": "embedding input is empty"}

    endpoint = settings.openai_base_url.rstrip("/") + "/embeddings"
    request_body = {
        "model": settings.embedding_model,
        "input": clean,
        "dimensions": settings.embedding_dimensions,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.model_request_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "fallback_reason": "openai_embedding_error", "error": detail}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"ok": False, "fallback_reason": "openai_embedding_error", "error": str(error)}

    embedding = ((response_payload.get("data") or [{}])[0] or {}).get("embedding")
    if not isinstance(embedding, list) or not embedding:
        return {"ok": False, "fallback_reason": "openai_embedding_empty", "error": "OpenAI embedding response did not include a vector"}
    vector = [float(value) for value in embedding]
    digest = hashlib.sha256(json.dumps(vector, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "payload": {
            "status": "ready",
            "provider": "openai",
            "model": response_payload.get("model") or settings.embedding_model,
            "dimensions": len(vector),
            "hash": digest,
            "vector": vector,
            "usage": response_payload.get("usage") or {},
        },
    }


def embedding_features(text: str) -> dict:
    normalized = "".join(char if char.isalnum() else " " for char in text.lower())
    features: dict[str, float] = {}
    for word in normalized.split():
        terms = [word]
        if len(word) > 1:
            terms.extend(word[index : index + 2] for index in range(len(word) - 1))
        if len(word) > 2:
            terms.extend(word[index : index + 3] for index in range(len(word) - 2))
        terms.extend(char for char in word if char.strip())
        for term in terms:
            key = hashlib.sha1(term.encode("utf-8")).hexdigest()[:12]
            features[key] = features.get(key, 0.0) + 1.0
    return features


def embedding_similarity(left: dict, right: dict) -> float:
    left_vector = left.get("vector") if isinstance(left.get("vector"), list) else []
    right_vector = right.get("vector") if isinstance(right.get("vector"), list) else []
    if left_vector and right_vector:
        return vector_cosine_similarity(left_vector, right_vector)
    left_features = left.get("features") if isinstance(left.get("features"), dict) else {}
    right_features = right.get("features") if isinstance(right.get("features"), dict) else {}
    if not left_features or not right_features:
        return 0.0
    shared = set(left_features).intersection(right_features)
    numerator = sum(float(left_features[key]) * float(right_features[key]) for key in shared)
    left_norm = sum(float(value) * float(value) for value in left_features.values()) ** 0.5
    right_norm = sum(float(value) * float(value) for value in right_features.values()) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def vector_cosine_similarity(left: list, right: list) -> float:
    size = min(len(left), len(right))
    if not size:
        return 0.0
    left_values = [float(value) for value in left[:size]]
    right_values = [float(value) for value in right[:size]]
    numerator = sum(left_values[index] * right_values[index] for index in range(size))
    left_norm = sum(value * value for value in left_values) ** 0.5
    right_norm = sum(value * value for value in right_values) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


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
    policy = resolve_output_policy(session, nullable_int(payload.get("policy_id")))
    selected_model = module.model
    if allow_model_override and payload.get("model_id"):
        override_model = session.get(ModelConfig, int(payload["model_id"]))
        if override_model is not None:
            selected_model = override_model
    elif policy is not None:
        selected_model = resolve_primary_model(session, policy, payload) or selected_model
    model_name = selected_model.display_name if selected_model else "未配置"
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
    provider_usage: dict = {}

    if force_fallback:
        final_json = build_fallback_json(module, knowledge_hits, fallback_reason)
        raw_response_text = json.dumps(
            {
                "fallback": True,
                "reason": fallback_reason,
                "summary": final_json["summary"],
            },
            ensure_ascii=False,
        )
        status = "fallback"
        fallback_triggered = True
    else:
        raw_response_text = ""
        model_output_handled = False
        if "simulate_model_response" in payload:
            raw_response_text = coerce_raw_model_response(payload.get("simulate_model_response"))
        elif should_call_live_model(payload):
            provider_result = call_model_provider(selected_model, model_request, module, policy)
            provider_usage = provider_result.get("usage") or {}
            raw_response_text = provider_result.get("raw_text") or ""
            if not provider_result.get("ok"):
                fallback_reason = provider_result.get("fallback_reason") or "model_provider_error"
                final_json = build_fallback_json(module, knowledge_hits, fallback_reason)
                final_json["provider_error"] = provider_result.get("error") or ""
                status = "fallback"
                fallback_triggered = True
                model_output_handled = True
            else:
                final_json, status, fallback_triggered, fallback_reason = validate_model_output(
                    module,
                    raw_response_text,
                    knowledge_hits,
                )
                model_output_handled = True
        if not raw_response_text and not model_output_handled:
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
            raw_response_text = json.dumps(
                {
                    "title": module.name,
                    "summary": summary,
                },
                ensure_ascii=False,
            )
            status = "ok"
            fallback_triggered = False
            fallback_reason = ""
        elif not model_output_handled:
            final_json, status, fallback_triggered, fallback_reason = validate_model_output(
                module,
                raw_response_text,
                knowledge_hits,
            )

    input_tokens = int(provider_usage.get("input_tokens") or max(1, len(model_request) // 4))
    output_tokens = int(provider_usage.get("output_tokens") or max(1, len(raw_response_text) // 4))
    trace = CallTrace(
        module_id=module.id,
        request_type=request_type,
        input_payload=payload,
        model_request=model_request,
        model_raw_response=raw_response_text,
        final_json=final_json,
        status=status,
        fallback_triggered=fallback_triggered,
        fallback_reason=fallback_reason if fallback_triggered else "",
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


def coerce_raw_model_response(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def should_call_live_model(payload: dict) -> bool:
    settings = get_settings()
    return bool(payload.get("use_live_model")) or settings.model_call_mode.lower() == "live"


def validate_model_output(module: Module, raw_response_text: str, knowledge_hits: list[dict]) -> tuple[dict, str, bool, str]:
    parsed, parse_error = parse_model_json(raw_response_text)
    if parse_error:
        return build_fallback_json(module, knowledge_hits, "invalid_json"), "fallback", True, "invalid_json"

    missing_fields = required_output_fields_missing(module, parsed)
    if missing_fields:
        fallback_json = build_fallback_json(module, knowledge_hits, "missing_required_fields")
        fallback_json["missing_fields"] = missing_fields
        return fallback_json, "fallback", True, "missing_required_fields"

    final_json = dict(parsed)
    final_json["module_id"] = module.id
    final_json["module_slug"] = module.slug
    final_json.setdefault("title", module.name)
    final_json.setdefault("knowledge_hits", knowledge_hits)
    return final_json, "ok", False, ""


def parse_model_json(raw_response_text: str) -> tuple[dict, str]:
    text = strip_json_fence(raw_response_text)
    if not text:
        return {}, "empty_response"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}, "invalid_json"
    if not isinstance(parsed, dict):
        return {}, "invalid_json"
    return parsed, ""


def strip_json_fence(raw_response_text: str) -> str:
    text = (raw_response_text or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    if lines and lines[0].strip().lower() == "json":
        lines = lines[1:]
    return "\n".join(lines).strip()


def required_output_fields_missing(module: Module, parsed: dict) -> list[str]:
    missing = []
    for field in module.fields:
        if not field.is_required or not field.is_ai_generated:
            continue
        value = parsed.get(field.field_name)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field.field_name)
    return missing


def build_fallback_json(module: Module, knowledge_hits: list[dict], reason: str) -> dict:
    summary = module.fallback_content or f"{module.name}暂时使用备用内容，请稍后重试。"
    return {
        "module_id": module.id,
        "module_slug": module.slug,
        "title": module.name,
        "summary": summary,
        "fallback": True,
        "fallback_reason": reason,
        "knowledge_hits": knowledge_hits,
    }


def call_model_provider(model: ModelConfig | None, model_request: str, module: Module, policy: OutputPolicy | None) -> dict:
    provider = (model.provider if model else "openai").lower()
    if provider != "openai":
        return {
            "ok": False,
            "fallback_reason": "unsupported_model_provider",
            "error": f"unsupported provider: {provider}",
            "raw_text": "",
        }
    return call_openai_responses_api(model, model_request, module, policy)


def call_openai_responses_api(model: ModelConfig | None, model_request: str, module: Module, policy: OutputPolicy | None) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        return {
            "ok": False,
            "fallback_reason": "provider_key_missing",
            "error": "NEXA_OPENAI_API_KEY is not configured",
            "raw_text": "",
        }

    endpoint = settings.openai_base_url.rstrip("/") + "/responses"
    request_body = {
        "model": model.name if model else "gpt-5.4-mini",
        "input": [{"role": "user", "content": model_request}],
        "store": False,
        "max_output_tokens": policy.max_output_tokens if policy else 600,
    }
    temperature = (policy.temperature_x100 if policy else 70) / 100
    if temperature >= 0:
        request_body["temperature"] = temperature
    if (policy.response_format if policy else "json") == "json":
        request_body["text"] = {"format": output_json_schema(module)}

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.model_request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "fallback_reason": "model_provider_error", "error": detail, "raw_text": detail}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"ok": False, "fallback_reason": "model_provider_error", "error": str(error), "raw_text": str(error)}

    raw_text = extract_openai_output_text(payload)
    usage = payload.get("usage") or {}
    return {
        "ok": bool(raw_text),
        "fallback_reason": "" if raw_text else "empty_model_response",
        "error": "" if raw_text else "OpenAI response did not include output text",
        "raw_text": raw_text,
        "usage": {
            "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
            "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens") or 0,
        },
    }


def output_json_schema(module: Module) -> dict:
    properties = {
        field.field_name: {
            "type": "string",
            "description": field.purpose or field.display_position or field.field_name,
        }
        for field in module.fields
    }
    required = [field.field_name for field in module.fields if field.is_required and field.is_ai_generated]
    return {
        "type": "json_schema",
        "name": f"nexa_{module.slug.replace('-', '_')[:40]}",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": properties or {"summary": {"type": "string"}},
            "required": required or ["summary"],
            "additionalProperties": True,
        },
    }


def extract_openai_output_text(payload: dict) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"]).strip()
    text_parts = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                text_parts.append(str(content["text"]))
    return "\n".join(text_parts).strip()


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


def create_or_update_app_user(session: Session, payload: dict) -> dict:
    external_id = (payload.get("external_id") or "").strip()
    if not external_id:
        raise ValueError("external_id is required")
    user = session.scalar(select(AppUser).where(AppUser.external_id == external_id))
    if user is None:
        user = AppUser(external_id=external_id)
        session.add(user)
    user.nickname = (payload.get("nickname") or user.nickname or "").strip()
    user.locale = (payload.get("locale") or user.locale or "zh-CN").strip()
    user.timezone = (payload.get("timezone") or user.timezone or "Asia/Shanghai").strip()
    user.status = (payload.get("status") or user.status or "active").strip()
    if isinstance(payload.get("profile"), dict):
        user.profile = payload["profile"]
    session.commit()
    session.refresh(user)
    return serialize_app_user(user)


def get_app_user(session: Session, user_id: int) -> dict | None:
    user = session.get(AppUser, user_id)
    return serialize_app_user(user) if user else None


def save_birth_profile(session: Session, user_id: int, payload: dict) -> dict | None:
    user = session.get(AppUser, user_id)
    if user is None:
        return None
    profile = session.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
    if profile is None:
        profile = BirthProfile(user_id=user.id)
        session.add(profile)
    profile.nickname = (payload.get("nickname") or profile.nickname or user.nickname or "").strip()
    profile.birth_date = (payload.get("birth_date") or profile.birth_date or "").strip()
    profile.birth_time = (payload.get("birth_time") or profile.birth_time or "").strip()
    profile.birth_city = (payload.get("birth_city") or profile.birth_city or "").strip()
    profile.birth_country = (payload.get("birth_country") or profile.birth_country or "").strip()
    profile.birth_timezone = (payload.get("birth_timezone") or payload.get("timezone") or profile.birth_timezone or user.timezone).strip()
    profile.latitude = str(payload.get("latitude") or profile.latitude or "").strip()
    profile.longitude = str(payload.get("longitude") or profile.longitude or "").strip()
    profile.raw_payload = merge_birth_profile_payload(profile.raw_payload or {}, payload)
    profile.chart_snapshot = build_chart_snapshot(profile)
    session.commit()
    session.refresh(profile)
    return serialize_birth_profile(profile)


def get_user_chart(session: Session, user_id: int) -> dict | None:
    user = session.get(AppUser, user_id)
    if user is None:
        return None
    profile = session.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
    warnings: list[str] = []
    if profile is None:
        warnings.append("用户还没有保存本命资料。")
        return {
            "user_id": user.id,
            "birth_profile": None,
            "chart_snapshot": {},
            "warnings": warnings,
        }
    snapshot = profile.chart_snapshot or build_chart_snapshot(profile)
    warnings.extend(snapshot.get("warnings") or [])
    return {
        "user_id": user.id,
        "birth_profile": serialize_birth_profile(profile),
        "chart_snapshot": snapshot,
        "warnings": warnings,
    }


def calculate_user_chart(session: Session, user_id: int, payload: dict) -> dict | None:
    if any(key in (payload or {}) for key in {"nickname", "birth_date", "birth_time", "birth_city", "birth_country", "birth_timezone", "timezone", "latitude", "longitude", "chart_system", "bazi_profile"}):
        saved = save_birth_profile(session, user_id, payload)
        if saved is None:
            return None

    user = session.get(AppUser, user_id)
    if user is None:
        return None
    profile = session.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
    if profile is None:
        return {
            "user_id": user.id,
            "birth_profile": None,
            "chart_snapshot": {},
            "warnings": ["用户还没有保存本命资料。"],
            "meta": {"mode": "snapshot", "provider": "local"},
        }

    requested_system = normalize_chart_system(payload.get("chart_system") or chart_system_from_profile(profile))
    if requested_system in {"bazi", "hybrid"}:
        if "simulate_algorithm_response" in payload:
            apply_bazi_algorithm_result(profile, normalize_bazi_algorithm_payload(payload.get("simulate_algorithm_response"), requested_system))
            meta = {"mode": "simulated", "provider": "bazi_calculator"}
        elif should_call_live_bazi(payload):
            provider_result = call_bazi_calculation_provider(profile, payload)
            if provider_result.get("ok"):
                apply_bazi_algorithm_result(profile, provider_result.get("payload") or {})
                meta = {"mode": "live", "provider": "bazi_calculator"}
            else:
                meta = {
                    "mode": "snapshot",
                    "provider": "bazi_calculator",
                    "fallback_reason": provider_result.get("fallback_reason") or "bazi_provider_error",
                    "error": provider_result.get("error") or "",
                }
        else:
            meta = {"mode": "snapshot", "provider": "local"}
    else:
        meta = {"mode": "snapshot", "provider": "local"}

    chart = get_user_chart(session, user_id) or {"user_id": user_id, "birth_profile": None, "chart_snapshot": {}, "warnings": []}
    chart["meta"] = meta
    return chart


def build_chart_snapshot(profile: BirthProfile) -> dict:
    system_type = chart_system_from_profile(profile)
    if system_type == "bazi":
        return build_bazi_chart_snapshot(profile)
    if system_type == "hybrid":
        return build_hybrid_chart_snapshot(profile)
    return build_astrology_chart_snapshot(profile)


def build_astrology_chart_snapshot(profile: BirthProfile) -> dict:
    warnings = ["当前版本为后端基础盘面快照，只计算太阳星座；完整宫位、上升、相位将在星盘计算服务阶段接入。"]
    sun_sign = sun_sign_from_birth_date(profile.birth_date)
    if not sun_sign:
        warnings.append("birth_date 无法解析，暂不能计算太阳星座。")
    if not profile.birth_time:
        warnings.append("缺少出生时间，后续无法精确计算上升和宫位。")
    if not profile.latitude or not profile.longitude:
        warnings.append("缺少出生地经纬度，后续无法精确计算宫位。")
    return {
        "system_type": "astrology",
        "calculation_level": "sun_sign_only",
        "sun_sign": sun_sign,
        "birth_datetime": " ".join(part for part in [profile.birth_date, profile.birth_time] if part),
        "birth_city": profile.birth_city,
        "birth_timezone": profile.birth_timezone,
        "warnings": warnings,
    }


def build_bazi_chart_snapshot(profile: BirthProfile) -> dict:
    bazi_profile = bazi_profile_from_profile(profile)
    pillars = bazi_pillars_from_profile(bazi_profile)
    warnings = ["当前版本为后端基础八字快照，使用输入的四柱与日主；大运、流年、藏干和旺衰将在八字计算服务阶段接入。"]
    if not all(pillars.values()):
        warnings.append("四柱信息还不完整，后续分析会受影响。")
    if not bazi_profile.get("day_master"):
        warnings.append("缺少日主信息，当前只能保留四柱原始输入。")
    if not profile.birth_time:
        warnings.append("缺少出生时间，时柱可能不准确。")
    return {
        "system_type": "bazi",
        "calculation_level": "bazi_input_only",
        "birth_datetime": " ".join(part for part in [profile.birth_date, profile.birth_time] if part),
        "birth_city": profile.birth_city,
        "birth_timezone": profile.birth_timezone,
        "pillars": pillars,
        "day_master": bazi_profile.get("day_master") or "",
        "five_elements": bazi_profile.get("five_elements") or {},
        "ten_gods": bazi_profile.get("ten_gods") or [],
        "warnings": warnings,
    }


def build_hybrid_chart_snapshot(profile: BirthProfile) -> dict:
    astrology = build_astrology_chart_snapshot(profile)
    bazi = build_bazi_chart_snapshot(profile)
    warnings = list(dict.fromkeys([*(astrology.get("warnings") or []), *(bazi.get("warnings") or [])]))
    return {
        "system_type": "hybrid",
        "calculation_level": "hybrid_foundation",
        "birth_datetime": astrology.get("birth_datetime") or bazi.get("birth_datetime") or "",
        "birth_city": profile.birth_city,
        "birth_timezone": profile.birth_timezone,
        "sun_sign": astrology.get("sun_sign") or "",
        "pillars": bazi.get("pillars") or {},
        "day_master": bazi.get("day_master") or "",
        "five_elements": bazi.get("five_elements") or {},
        "ten_gods": bazi.get("ten_gods") or [],
        "warnings": warnings,
    }


def merge_birth_profile_payload(existing: dict, payload: dict) -> dict:
    merged = dict(existing or {})
    for key, value in (payload or {}).items():
        if key == "bazi_profile" and isinstance(value, dict):
            current = merged.get("bazi_profile") if isinstance(merged.get("bazi_profile"), dict) else {}
            merged["bazi_profile"] = {**current, **value}
        else:
            merged[key] = value
    return merged


def chart_system_from_profile(profile: BirthProfile) -> str:
    raw = profile.raw_payload or {}
    system = normalize_chart_system(raw.get("chart_system") or raw.get("reading_system") or "")
    if system in {"bazi", "hybrid", "astrology"}:
        return system
    if isinstance(raw.get("bazi_profile"), dict):
        return "bazi"
    return "astrology"


def normalize_chart_system(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in {"astrology", "bazi", "hybrid"} else "astrology"


def bazi_profile_from_profile(profile: BirthProfile) -> dict:
    raw = profile.raw_payload or {}
    bazi_profile = raw.get("bazi_profile") if isinstance(raw.get("bazi_profile"), dict) else {}
    return {
        "year_pillar": str(bazi_profile.get("year_pillar") or "").strip(),
        "month_pillar": str(bazi_profile.get("month_pillar") or "").strip(),
        "day_pillar": str(bazi_profile.get("day_pillar") or "").strip(),
        "hour_pillar": str(bazi_profile.get("hour_pillar") or "").strip(),
        "day_master": str(bazi_profile.get("day_master") or "").strip(),
        "five_elements": bazi_profile.get("five_elements") if isinstance(bazi_profile.get("five_elements"), dict) else {},
        "ten_gods": bazi_profile.get("ten_gods") if isinstance(bazi_profile.get("ten_gods"), list) else [],
    }


def bazi_pillars_from_profile(bazi_profile: dict) -> dict:
    return {
        "year": str(bazi_profile.get("year_pillar") or "").strip(),
        "month": str(bazi_profile.get("month_pillar") or "").strip(),
        "day": str(bazi_profile.get("day_pillar") or "").strip(),
        "hour": str(bazi_profile.get("hour_pillar") or "").strip(),
    }


def normalize_bazi_algorithm_payload(value, requested_system: str = "bazi") -> dict:
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("simulate_algorithm_response 不是有效 JSON") from exc
    elif isinstance(value, dict):
        payload = value
    else:
        raise ValueError("simulate_algorithm_response 必须是 JSON 对象或 JSON 字符串")

    bazi_profile = payload.get("bazi_profile") if isinstance(payload.get("bazi_profile"), dict) else payload
    pillars = payload.get("pillars") if isinstance(payload.get("pillars"), dict) else {}
    return {
        "chart_system": normalize_chart_system(payload.get("chart_system") or requested_system),
        "bazi_profile": {
            "year_pillar": str(bazi_profile.get("year_pillar") or pillars.get("year") or "").strip(),
            "month_pillar": str(bazi_profile.get("month_pillar") or pillars.get("month") or "").strip(),
            "day_pillar": str(bazi_profile.get("day_pillar") or pillars.get("day") or "").strip(),
            "hour_pillar": str(bazi_profile.get("hour_pillar") or pillars.get("hour") or "").strip(),
            "day_master": str(bazi_profile.get("day_master") or "").strip(),
            "five_elements": bazi_profile.get("five_elements") if isinstance(bazi_profile.get("five_elements"), dict) else {},
            "ten_gods": bazi_profile.get("ten_gods") if isinstance(bazi_profile.get("ten_gods"), list) else [],
        },
    }


def apply_bazi_algorithm_result(profile: BirthProfile, payload: dict) -> None:
    merged_payload = merge_birth_profile_payload(profile.raw_payload or {}, payload)
    merged_payload["chart_system"] = normalize_chart_system(payload.get("chart_system") or merged_payload.get("chart_system") or "bazi")
    profile.raw_payload = merged_payload
    profile.chart_snapshot = build_chart_snapshot(profile)
    profile.updated_at = utc_now()
    session = Session.object_session(profile)
    if session is not None:
        session.add(profile)
        session.commit()
        session.refresh(profile)


def should_call_live_bazi(payload: dict) -> bool:
    settings = get_settings()
    return bool(payload.get("use_live_bazi")) or settings.bazi_calc_mode.lower() == "live"


def call_bazi_calculation_provider(profile: BirthProfile, payload: dict) -> dict:
    settings = get_settings()
    if not settings.bazi_api_url:
        return {"ok": False, "fallback_reason": "bazi_provider_missing", "error": "NEXA_BAZI_API_URL is not configured"}

    request_body = {
        "chart_system": normalize_chart_system(payload.get("chart_system") or chart_system_from_profile(profile)),
        "birth_date": profile.birth_date,
        "birth_time": profile.birth_time,
        "birth_city": profile.birth_city,
        "birth_country": profile.birth_country,
        "birth_timezone": profile.birth_timezone,
        "latitude": profile.latitude,
        "longitude": profile.longitude,
    }
    headers = {"Content-Type": "application/json"}
    if settings.bazi_api_token:
        headers["Authorization"] = f"Bearer {settings.bazi_api_token}"
    request = urllib.request.Request(
        settings.bazi_api_url,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.bazi_request_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "fallback_reason": "bazi_provider_error", "error": detail}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"ok": False, "fallback_reason": "bazi_provider_error", "error": str(error)}

    try:
        normalized = normalize_bazi_algorithm_payload(response_payload, request_body["chart_system"])
    except ValueError as exc:
        return {"ok": False, "fallback_reason": "bazi_provider_invalid_payload", "error": str(exc)}
    return {"ok": True, "payload": normalized}


def sun_sign_from_birth_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(str(value or "").strip())
    except ValueError:
        return ""
    month_day = (parsed.month, parsed.day)
    signs = [
        ("摩羯座", (1, 1), (1, 19)),
        ("水瓶座", (1, 20), (2, 18)),
        ("双鱼座", (2, 19), (3, 20)),
        ("白羊座", (3, 21), (4, 19)),
        ("金牛座", (4, 20), (5, 20)),
        ("双子座", (5, 21), (6, 21)),
        ("巨蟹座", (6, 22), (7, 22)),
        ("狮子座", (7, 23), (8, 22)),
        ("处女座", (8, 23), (9, 22)),
        ("天秤座", (9, 23), (10, 23)),
        ("天蝎座", (10, 24), (11, 22)),
        ("射手座", (11, 23), (12, 21)),
        ("摩羯座", (12, 22), (12, 31)),
    ]
    for sign, start, end in signs:
        if start <= month_day <= end:
            return sign
    return ""


def create_chat_session(session: Session, payload: dict) -> dict | None:
    user = session.get(AppUser, nullable_int(payload.get("user_id")) or 0)
    if user is None:
        return None
    chat_session = ChatSession(
        user_id=user.id,
        title=(payload.get("title") or "新的咨询").strip(),
        topic=(payload.get("topic") or "").strip(),
        status=(payload.get("status") or "active").strip(),
        metadata_json=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    return serialize_chat_session(chat_session, include_messages=True)


def get_chat_session(session: Session, session_id: int) -> dict | None:
    chat_session = session.scalar(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages), joinedload(ChatSession.user))
    )
    return serialize_chat_session(chat_session, include_messages=True) if chat_session else None


def append_chat_message(session: Session, session_id: int, payload: dict) -> dict | None:
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        return None
    role = (payload.get("role") or "user").strip()
    if role not in {"user", "assistant", "system", "tool"}:
        raise ValueError("message role is invalid")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("message content is required")
    message = ChatMessage(
        session_id=chat_session.id,
        user_id=chat_session.user_id,
        role=role,
        content=content,
        metadata_json=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        token_count=max(1, len(content) // 4),
    )
    chat_session.updated_at = utc_now()
    session.add(message)
    session.commit()
    session.refresh(message)
    return serialize_chat_message(message)


def upsert_memory_summary(session: Session, user_id: int, payload: dict) -> dict | None:
    user = session.get(AppUser, user_id)
    if user is None:
        return None
    summary = session.scalar(select(UserMemorySummary).where(UserMemorySummary.user_id == user.id))
    if summary is None:
        summary = UserMemorySummary(user_id=user.id)
        session.add(summary)
    else:
        summary.version += 1
    summary.summary = str(payload.get("summary") or "").strip()
    summary.metadata_json = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    session.commit()
    session.refresh(summary)
    return serialize_memory_summary(summary)


def create_memory_item(session: Session, user_id: int, payload: dict) -> dict | None:
    user = session.get(AppUser, user_id)
    if user is None:
        return None
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("memory content is required")
    item = MemoryItem(
        user_id=user.id,
        source_session_id=nullable_int(payload.get("source_session_id")),
        memory_type=(payload.get("memory_type") or "preference").strip(),
        content=content,
        tags=normalize_tags(payload.get("tags") or []),
        importance=clamp_int(payload.get("importance"), 1, 5, 3),
        status=(payload.get("status") or "active").strip(),
    )
    apply_text_embedding(item, f"{item.memory_type}\n{item.content}")
    session.add(item)
    session.flush()
    sync_pgvector_embedding(session, "memory_items", item.id, item.embedding_payload)
    session.commit()
    session.refresh(item)
    return serialize_memory_item(item)


def list_user_memories(session: Session, user_id: int) -> dict | None:
    user = session.get(AppUser, user_id)
    if user is None:
        return None
    summary = session.scalar(select(UserMemorySummary).where(UserMemorySummary.user_id == user.id))
    items = session.scalars(
        select(MemoryItem)
        .where(MemoryItem.user_id == user.id, MemoryItem.status == "active")
        .order_by(MemoryItem.importance.desc(), MemoryItem.updated_at.desc(), MemoryItem.id.desc())
    ).all()
    return {
        "user_id": user.id,
        "summary": serialize_memory_summary(summary) if summary else None,
        "items": [serialize_memory_item(item) for item in items],
    }


def serialize_app_user(user: AppUser) -> dict:
    return {
        "id": user.id,
        "external_id": user.external_id,
        "nickname": user.nickname,
        "locale": user.locale,
        "timezone": user.timezone,
        "status": user.status,
        "profile": user.profile or {},
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def serialize_birth_profile(profile: BirthProfile) -> dict:
    chart_system = chart_system_from_profile(profile)
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "nickname": profile.nickname,
        "birth_date": profile.birth_date,
        "birth_time": profile.birth_time,
        "birth_city": profile.birth_city,
        "birth_country": profile.birth_country,
        "birth_timezone": profile.birth_timezone,
        "latitude": profile.latitude,
        "longitude": profile.longitude,
        "chart_system": chart_system,
        "bazi_profile": bazi_profile_from_profile(profile) if chart_system in {"bazi", "hybrid"} else {},
        "chart_snapshot": profile.chart_snapshot or {},
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def serialize_chat_session(chat_session: ChatSession, include_messages: bool = False) -> dict:
    data = {
        "id": chat_session.id,
        "user_id": chat_session.user_id,
        "title": chat_session.title,
        "topic": chat_session.topic,
        "status": chat_session.status,
        "metadata": chat_session.metadata_json or {},
        "created_at": chat_session.created_at.isoformat(),
        "updated_at": chat_session.updated_at.isoformat(),
    }
    if include_messages:
        data["messages"] = [serialize_chat_message(message) for message in sorted(chat_session.messages, key=lambda item: item.id)]
    return data


def serialize_chat_message(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "user_id": message.user_id,
        "role": message.role,
        "content": message.content,
        "metadata": message.metadata_json or {},
        "token_count": message.token_count,
        "created_at": message.created_at.isoformat(),
    }


def serialize_memory_summary(summary: UserMemorySummary) -> dict:
    return {
        "id": summary.id,
        "user_id": summary.user_id,
        "summary": summary.summary,
        "version": summary.version,
        "metadata": summary.metadata_json or {},
        "created_at": summary.created_at.isoformat(),
        "updated_at": summary.updated_at.isoformat(),
    }


def serialize_memory_item(item: MemoryItem) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "source_session_id": item.source_session_id,
        "memory_type": item.memory_type,
        "content": item.content,
        "tags": item.tags or [],
        "importance": item.importance,
        "status": item.status,
        "embedding": serialize_embedding_meta(item),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def generate_chat_reply(session: Session, session_id: int, payload: dict) -> dict | None:
    chat_session = load_chat_session_model(session, session_id)
    if chat_session is None:
        return None
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("reply content is required")

    user_message = append_chat_message(session, session_id, {"role": "user", "content": content, "metadata": payload.get("user_message_metadata") or {}})
    context = build_chat_context(session, session_id, content, payload)
    model_request = build_chat_model_request(context, content, payload)
    answer, mode, provider_meta = resolve_chat_answer(model_request, context, content, payload)
    assistant_message = append_chat_message(
        session,
        session_id,
        {
            "role": "assistant",
            "content": answer,
            "metadata": {
                "mode": mode,
                "provider": provider_meta,
                "knowledge_hit_ids": [item["id"] for item in context["knowledge_hits"]],
            },
        },
    )
    memory_updates = extract_and_store_chat_memories(
        session,
        chat_session.user_id,
        session_id,
        content,
        answer,
        payload,
    )
    return {
        "session_id": session_id,
        "status": "ok" if mode != "fallback" else "fallback",
        "answer": answer,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "memory_updates": memory_updates,
        "context": context,
        "meta": {
            "mode": mode,
            "model_request": model_request,
            "provider": provider_meta,
        },
    }


def normalize_memory_run_mode(payload: dict) -> str:
    return "queued" if str(payload.get("memory_run_mode") or "").strip().lower() == "queued" else "sync"


def extract_and_store_chat_memories(
    session: Session,
    user_id: int,
    session_id: int,
    user_content: str,
    assistant_answer: str,
    payload: dict,
) -> dict:
    if payload.get("memory_extraction") is False or payload.get("auto_memory") is False:
        existing = session.scalar(select(UserMemorySummary).where(UserMemorySummary.user_id == user_id))
        return {
            "created_count": 0,
            "items": [],
            "summary": serialize_memory_summary(existing) if existing else None,
            "summary_status": "skipped",
            "task_id": None,
        }

    candidates = extract_memory_candidates(user_content, assistant_answer)
    created_items = []
    for candidate in candidates:
        item = create_memory_item(
            session,
            user_id,
            {
                **candidate,
                "source_session_id": session_id,
            },
        )
        if item is not None:
            created_items.append(item)

    existing = session.scalar(select(UserMemorySummary).where(UserMemorySummary.user_id == user_id))
    if not created_items:
        return {
            "created_count": 0,
            "items": [],
            "summary": serialize_memory_summary(existing) if existing else None,
            "summary_status": "unchanged",
            "task_id": None,
        }

    if normalize_memory_run_mode(payload) == "queued":
        task = TaskEnvelope(
            task_type="memory.summarize",
            payload={"user_id": user_id, "memory_item_ids": [item["id"] for item in created_items]},
        )
        task_id = get_task_queue().enqueue(task)
        return {
            "created_count": len(created_items),
            "items": created_items,
            "summary": serialize_memory_summary(existing) if existing else None,
            "summary_status": "queued",
            "task_id": task_id,
        }

    summary = update_memory_summary_from_candidates(session, user_id, created_items)
    return {
        "created_count": len(created_items),
        "items": created_items,
        "summary": summary,
        "summary_status": "updated",
        "task_id": None,
    }


def extract_memory_candidates(user_content: str, assistant_answer: str) -> list[dict]:
    text = " ".join(str(user_content or "").split())
    answer = " ".join(str(assistant_answer or "").split())
    candidates: list[dict] = []

    def add(memory_type: str, content: str, tags: list[str], importance: int) -> None:
        clean = compact_text(content, 140)
        if not clean:
            return
        if any(item["content"] == clean for item in candidates):
            return
        candidates.append(
            {
                "memory_type": memory_type,
                "content": clean,
                "tags": tags,
                "importance": importance,
            }
        )

    if any(keyword in text for keyword in ["喜欢", "偏好", "希望", "更温和", "短回复", "先给结论"]):
        add("preference", f"用户表达了回复偏好：{text}", ["偏好", "表达"], 4)
    if "最近" in text:
        add("current_state", f"用户最近状态：{text}", ["近况"], 4)
    if any(keyword in text for keyword in ["合作", "项目", "事业", "工作"]):
        add("current_state", f"用户当前关注合作/事业议题：{text}", ["合作", "事业"], 4)
    if any(keyword in text for keyword in ["伴侣", "关系", "恋爱", "沟通", "边界"]):
        add("relationship", f"用户关系议题线索：{text}", ["关系", "边界"], 4)
    if any(keyword in answer for keyword in ["边界", "节奏", "温和"]):
        add("assistant_observation", f"本轮回复有效线索：{answer}", ["回复线索"], 2)

    return candidates[:5]


def update_memory_summary_from_candidates(session: Session, user_id: int, items: list[dict]) -> dict | None:
    existing = session.scalar(select(UserMemorySummary).where(UserMemorySummary.user_id == user_id))
    if not items:
        return serialize_memory_summary(existing) if existing else None

    fragments = []
    if existing and existing.summary:
        fragments.append(existing.summary)
    for item in items:
        content = item["content"]
        if content not in "；".join(fragments):
            fragments.append(content)
    summary_text = compact_text("；".join(fragments), 520)
    return upsert_memory_summary(session, user_id, {"summary": summary_text, "metadata": {"source": "auto_chat_memory"}})


def execute_memory_summary_job(session: Session, user_id: int, memory_item_ids: list[int] | None = None) -> dict | None:
    user = session.get(AppUser, user_id)
    if user is None:
        return None

    query = select(MemoryItem).where(MemoryItem.user_id == user.id, MemoryItem.status == "active")
    if memory_item_ids:
        query = query.where(MemoryItem.id.in_(memory_item_ids))
    items = session.scalars(query.order_by(MemoryItem.importance.desc(), MemoryItem.updated_at.desc(), MemoryItem.id.desc())).all()
    return update_memory_summary_from_candidates(session, user.id, [serialize_memory_item(item) for item in items])


def load_chat_session_model(session: Session, session_id: int) -> ChatSession | None:
    return session.scalar(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(joinedload(ChatSession.user), selectinload(ChatSession.messages))
    )


def build_chat_context(session: Session, session_id: int, content: str, payload: dict) -> dict:
    chat_session = load_chat_session_model(session, session_id)
    user = chat_session.user
    chart = get_user_chart(session, user.id) or {"birth_profile": None, "chart_snapshot": {}, "warnings": []}
    memory = list_user_memories(session, user.id) or {"summary": None, "items": []}
    tags = normalize_tags(payload.get("knowledge_tags") or [])
    knowledge_hits = search_knowledge(session, {"query": content, "tags": tags, "limit": int(payload.get("knowledge_limit") or 5)})
    recent_messages = [
        serialize_chat_message(message)
        for message in sorted(chat_session.messages, key=lambda item: item.id)[-8:]
    ]
    return {
        "user": serialize_app_user(user),
        "birth_profile": chart.get("birth_profile"),
        "chart_snapshot": chart.get("chart_snapshot") or {},
        "chart_warnings": chart.get("warnings") or [],
        "memory": memory,
        "recent_messages": recent_messages,
        "knowledge_hits": knowledge_hits,
    }


def build_chat_model_request(context: dict, content: str, payload: dict) -> str:
    memory_summary = (context.get("memory") or {}).get("summary") or {}
    memory_items = (context.get("memory") or {}).get("items") or []
    lines = [
        "你是 Nexa 占星/八字咨询后端回复 Agent。",
        "要求：温暖、清晰、不过度绝对化；不得输出医疗、法律、投资等高风险承诺。",
        f"输出档位：{payload.get('quality_tier') or 'standard'}",
        "",
        f"用户：{context['user'].get('nickname') or context['user'].get('external_id')}",
        f"盘面快照：{json.dumps(context.get('chart_snapshot') or {}, ensure_ascii=False)}",
        f"长期记忆摘要：{memory_summary.get('summary') or ''}",
        f"可检索记忆：{json.dumps(memory_items[:5], ensure_ascii=False)}",
        f"知识库命中：{json.dumps(context.get('knowledge_hits') or [], ensure_ascii=False)}",
        f"最近消息：{json.dumps(context.get('recent_messages') or [], ensure_ascii=False)}",
        "",
        f"用户本轮问题：{content}",
        "请直接给出可发送给用户的中文回复。",
    ]
    return "\n".join(lines)


def resolve_chat_answer(model_request: str, context: dict, content: str, payload: dict) -> tuple[str, str, dict]:
    if "simulate_model_response" in payload:
        return coerce_raw_model_response(payload.get("simulate_model_response")).strip(), "simulated", {}
    if should_call_live_model(payload):
        provider_result = call_chat_model_provider(model_request, payload)
        if provider_result.get("ok"):
            return provider_result.get("raw_text") or "", "live", provider_result.get("usage") or {}
        answer = build_mock_chat_answer(context, content)
        return answer, "fallback", {"error": provider_result.get("error") or "", "fallback_reason": provider_result.get("fallback_reason") or ""}
    return build_mock_chat_answer(context, content), "mock", {}


def build_mock_chat_answer(context: dict, content: str) -> str:
    user = context.get("user") or {}
    nickname = user.get("nickname") or "你好"
    chart_snapshot = context.get("chart_snapshot") or {}
    system_type = chart_snapshot.get("system_type") or "astrology"
    sun_sign = chart_snapshot.get("sun_sign") or "你的太阳星座"
    day_master = chart_snapshot.get("day_master") or "你的日主"
    pillars = chart_snapshot.get("pillars") or {}
    memory_summary = ((context.get("memory") or {}).get("summary") or {}).get("summary") or ""
    knowledge_hint = ""
    if context.get("knowledge_hits"):
        knowledge_hint = f"我会参考「{context['knowledge_hits'][0]['title']}」这条规则，"
    memory_hint = "结合你过往偏好，" if memory_summary else ""
    if system_type == "bazi":
        pillar_hint = "/".join(filter(None, [pillars.get("year"), pillars.get("month"), pillars.get("day"), pillars.get("hour")]))
        pillar_text = f"四柱里先看到{pillar_hint}，" if pillar_hint else ""
        return (
            f"{nickname}，我先给结论：这件事可以推进，但不要一下子把力出尽。"
            f"从八字基础信息看，你的日主是{day_master}，{pillar_text}更适合先稳住节奏，再决定要不要继续加码。"
            f"{memory_hint}{knowledge_hint}针对“{content}”，建议先确认现实条件和合作边界，再决定主动推进到什么程度。"
        )
    if system_type == "hybrid":
        return (
            f"{nickname}，我先给结论：这件事可以推进，但要同时顾到节奏和边界。"
            f"你现在的基础资料里，太阳星座是{sun_sign}，八字日主是{day_master}，更适合先看清局势，再做清晰表达。"
            f"{memory_hint}{knowledge_hint}针对“{content}”，建议先做一轮确认，再决定是否继续加大投入。"
        )
    return (
        f"{nickname}，我先给结论：这件事可以推进，但要保留节奏感。"
        f"你当前基础盘面显示太阳在{sun_sign}，更适合用清晰、对等的方式表达。"
        f"{memory_hint}{knowledge_hint}今天先做一个小确认，比一次性把话说满更稳。"
        f"针对“{content}”，建议先问清对方期待，再决定投入多少资源。"
    )


def call_chat_model_provider(model_request: str, payload: dict) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        return {"ok": False, "fallback_reason": "provider_key_missing", "error": "NEXA_OPENAI_API_KEY is not configured", "raw_text": ""}
    endpoint = settings.openai_base_url.rstrip("/") + "/responses"
    request_body = {
        "model": payload.get("model_name") or "gpt-5.4-mini",
        "input": [{"role": "user", "content": model_request}],
        "store": False,
        "max_output_tokens": int(payload.get("max_output_tokens") or 700),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.model_request_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "fallback_reason": "model_provider_error", "error": detail, "raw_text": detail}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"ok": False, "fallback_reason": "model_provider_error", "error": str(error), "raw_text": str(error)}

    raw_text = extract_openai_output_text(response_payload)
    usage = response_payload.get("usage") or {}
    return {
        "ok": bool(raw_text),
        "fallback_reason": "" if raw_text else "empty_model_response",
        "error": "" if raw_text else "OpenAI response did not include output text",
        "raw_text": raw_text,
        "usage": {
            "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
            "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens") or 0,
        },
    }


def chat_reply_sse_events(reply: dict):
    yield sse_event("meta", {"session_id": reply["session_id"], "status": reply["status"], "mode": reply["meta"]["mode"]})
    answer = reply.get("answer") or ""
    chunk_size = 12
    for start in range(0, len(answer), chunk_size):
        yield sse_event("delta", {"text": answer[start : start + chunk_size]})
    yield sse_event("memory", reply.get("memory_updates") or {"created_count": 0, "items": [], "summary": None})
    yield sse_event("done", {"assistant_message_id": reply["assistant_message"]["id"], "answer": answer})


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def enrich_app_render_payload(session: Session, payload: dict) -> dict:
    enriched = dict(payload or {})
    input_payload = dict(enriched.get("input_payload") or {})
    render_date = str(enriched.get("date") or input_payload.get("date") or "").strip()
    if render_date:
        input_payload.setdefault("date", render_date)
    try:
        user_id = nullable_int(enriched.get("user_id"))
    except (TypeError, ValueError):
        user_id = None

    if user_id is not None:
        user = session.get(AppUser, user_id)
        if user is not None:
            input_payload.setdefault("user_profile", serialize_app_user(user))
        chart = get_user_chart(session, user_id)
        if chart is not None:
            chart_snapshot = chart.get("chart_snapshot") or {}
            input_payload.setdefault("birth_profile", chart.get("birth_profile"))
            input_payload.setdefault("chart_snapshot", chart_snapshot)
            input_payload.setdefault("chart_warnings", chart.get("warnings") or [])
            enrich_chart_facts(input_payload, chart_snapshot, render_date)

    enriched["input_payload"] = input_payload
    return enriched


def enrich_chart_facts(input_payload: dict, chart_snapshot: dict, render_date: str = "") -> None:
    system_type = chart_snapshot.get("system_type") or ""
    if system_type in {"astrology", "hybrid"} or chart_snapshot.get("sun_sign"):
        input_payload.setdefault("astrology_facts", chart_snapshot)
        input_payload.setdefault("sun_sign", chart_snapshot.get("sun_sign") or "")

    if system_type in {"bazi", "hybrid"} or chart_snapshot.get("day_master") or chart_snapshot.get("pillars"):
        pillars = chart_snapshot.get("pillars") if isinstance(chart_snapshot.get("pillars"), dict) else {}
        input_payload.setdefault("bazi_facts", chart_snapshot)
        input_payload.setdefault("bazi_profile", bazi_profile_payload_from_snapshot(chart_snapshot))
        input_payload.setdefault("pillars", pillars)
        input_payload.setdefault("day_master", chart_snapshot.get("day_master") or "")
        input_payload.setdefault("year_pillar", pillars.get("year") or "")
        input_payload.setdefault("month_pillar", pillars.get("month") or "")
        input_payload.setdefault("day_pillar", pillars.get("day") or "")
        input_payload.setdefault("hour_pillar", pillars.get("hour") or "")
        if render_date:
            input_payload.setdefault("daily_transit", build_bazi_daily_transit(render_date, chart_snapshot))


def bazi_profile_payload_from_snapshot(chart_snapshot: dict) -> dict:
    pillars = chart_snapshot.get("pillars") if isinstance(chart_snapshot.get("pillars"), dict) else {}
    return {
        "year_pillar": pillars.get("year") or "",
        "month_pillar": pillars.get("month") or "",
        "day_pillar": pillars.get("day") or "",
        "hour_pillar": pillars.get("hour") or "",
        "day_master": chart_snapshot.get("day_master") or "",
        "five_elements": chart_snapshot.get("five_elements") if isinstance(chart_snapshot.get("five_elements"), dict) else {},
        "ten_gods": chart_snapshot.get("ten_gods") if isinstance(chart_snapshot.get("ten_gods"), list) else [],
    }


def build_bazi_daily_transit(render_date: str, chart_snapshot: dict) -> dict:
    pillars = chart_snapshot.get("pillars") if isinstance(chart_snapshot.get("pillars"), dict) else {}
    return {
        "system_type": "bazi_daily",
        "date": render_date,
        "base_day_master": chart_snapshot.get("day_master") or "",
        "base_pillars": pillars,
        "calculation_level": "daily_transit_placeholder",
        "source": "local_placeholder",
        "warnings": ["当前版本尚未接入真实流日/流月计算服务，daily_transit 仅用于稳定接口和提示词上下文。"],
    }


def render_app_module(session: Session, module_slug: str, payload: dict, request_id: str | None = None) -> dict | None:
    module = session.scalar(
        select(Module)
        .where(Module.slug == module_slug)
        .options(joinedload(Module.page), joinedload(Module.model), joinedload(Module.prompt), selectinload(Module.fields))
    )
    if module is None or module.status not in APP_ACTIVE_STATUSES:
        return None

    resolved_request_id = request_id or new_request_id()
    enriched_payload = enrich_app_render_payload(session, payload)
    trace_payload = {**enriched_payload, "request_id": resolved_request_id}
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
    enriched_payload = enrich_app_render_payload(session, payload)
    modules = sorted((module for module in page.modules if module.status in APP_ACTIVE_STATUSES), key=lambda module: module.id)
    rendered_modules = []
    for module in modules:
        trace = run_module_trace(session, module, {**enriched_payload, "request_id": request_id}, "official")
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


def create_model_provider_key(session: Session, payload: dict) -> dict:
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        api_key = f"mk_{secrets.token_urlsafe(32)}"
    key = ModelProviderKey(
        name=(payload.get("name") or "未命名模型 Key").strip(),
        provider=(payload.get("provider") or "openai").strip(),
        token_hash=hash_token(api_key),
        token_prefix=api_key[:12],
        created_by=payload.get("operator") or "admin",
        status=ModelProviderKeyStatus.active.value,
    )
    session.add(key)
    session.commit()
    session.refresh(key)
    record_audit_event(
        session,
        event_type="model_provider_key_created",
        actor=key.created_by,
        target_type="model_provider_key",
        target_id=str(key.id),
        severity="info",
        details={"name": key.name, "provider": key.provider},
    )
    return {"api_key": api_key, "key": serialize_model_provider_key(key)}


def list_model_provider_keys(session: Session) -> list[dict]:
    keys = session.scalars(select(ModelProviderKey).order_by(ModelProviderKey.created_at.desc(), ModelProviderKey.id.desc())).all()
    return [serialize_model_provider_key(key) for key in keys]


def revoke_model_provider_key(session: Session, key_id: int, payload: dict) -> dict | None:
    key = session.get(ModelProviderKey, key_id)
    if key is None:
        return None
    key.status = ModelProviderKeyStatus.revoked.value
    key.revoked_at = utc_now()
    session.commit()
    session.refresh(key)
    record_audit_event(
        session,
        event_type="model_provider_key_revoked",
        actor=payload.get("operator") or "admin",
        target_type="model_provider_key",
        target_id=str(key.id),
        severity="warning",
        details={"name": key.name, "provider": key.provider},
    )
    return serialize_model_provider_key(key)


def serialize_model_provider_key(key: ModelProviderKey) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "provider": key.provider,
        "token_prefix": key.token_prefix,
        "status": key.status,
        "created_by": key.created_by,
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


def create_output_policy(session: Session, payload: dict) -> dict:
    policy = OutputPolicy(
        name=(payload.get("name") or "默认输出策略").strip(),
        quality_tier=(payload.get("quality_tier") or "standard").strip(),
        primary_model_id=nullable_int(payload.get("primary_model_id")),
        fallback_model_id=nullable_int(payload.get("fallback_model_id")),
        max_output_tokens=clamp_int(payload.get("max_output_tokens"), 120, 4000, 600),
        temperature_x100=clamp_int(payload.get("temperature_x100"), 0, 200, 70),
        response_format=(payload.get("response_format") or "json").strip(),
        safety_rules=payload.get("safety_rules") or "",
        is_default=bool(payload.get("is_default")),
    )
    if policy.is_default:
        clear_default_output_policies(session)
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return serialize_output_policy(policy)


def update_output_policy(session: Session, policy_id: int, payload: dict) -> dict | None:
    policy = session.scalar(
        select(OutputPolicy)
        .where(OutputPolicy.id == policy_id)
        .options(joinedload(OutputPolicy.primary_model), joinedload(OutputPolicy.fallback_model))
    )
    if policy is None:
        return None
    if "name" in payload:
        policy.name = (payload.get("name") or policy.name).strip()
    if "quality_tier" in payload:
        policy.quality_tier = (payload.get("quality_tier") or policy.quality_tier).strip()
    if "primary_model_id" in payload:
        policy.primary_model_id = nullable_int(payload.get("primary_model_id"))
    if "fallback_model_id" in payload:
        policy.fallback_model_id = nullable_int(payload.get("fallback_model_id"))
    if "max_output_tokens" in payload:
        policy.max_output_tokens = clamp_int(payload.get("max_output_tokens"), 120, 4000, policy.max_output_tokens)
    if "temperature_x100" in payload:
        policy.temperature_x100 = clamp_int(payload.get("temperature_x100"), 0, 200, policy.temperature_x100)
    if "response_format" in payload:
        policy.response_format = (payload.get("response_format") or policy.response_format).strip()
    if "safety_rules" in payload:
        policy.safety_rules = payload.get("safety_rules") or ""
    if "is_default" in payload:
        policy.is_default = bool(payload.get("is_default"))
        if policy.is_default:
            clear_default_output_policies(session, except_id=policy.id)
    session.commit()
    session.refresh(policy)
    return serialize_output_policy(policy)


def list_output_policies(session: Session) -> list[dict]:
    policies = session.scalars(
        select(OutputPolicy)
        .options(joinedload(OutputPolicy.primary_model), joinedload(OutputPolicy.fallback_model))
        .order_by(OutputPolicy.is_default.desc(), OutputPolicy.created_at.desc(), OutputPolicy.id.desc())
    ).all()
    return [serialize_output_policy(policy) for policy in policies]


def clear_default_output_policies(session: Session, except_id: int | None = None) -> None:
    policies = session.scalars(select(OutputPolicy).where(OutputPolicy.is_default.is_(True))).all()
    for policy in policies:
        if except_id is None or policy.id != except_id:
            policy.is_default = False


def serialize_output_policy(policy: OutputPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "quality_tier": policy.quality_tier,
        "primary_model_id": policy.primary_model_id,
        "fallback_model_id": policy.fallback_model_id,
        "primary_model": serialize_model_config(policy.primary_model),
        "fallback_model": serialize_model_config(policy.fallback_model),
        "max_output_tokens": policy.max_output_tokens,
        "temperature_x100": policy.temperature_x100,
        "response_format": policy.response_format,
        "safety_rules": policy.safety_rules,
        "is_default": policy.is_default,
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


def preview_model_route(session: Session, payload: dict) -> dict:
    policy = resolve_output_policy(session, nullable_int(payload.get("policy_id")))
    module = session.get(Module, nullable_int(payload.get("module_id")) or 0)
    selected_model = resolve_primary_model(session, policy, payload)
    fallback_model = resolve_fallback_model(session, policy, selected_model)
    return {
        "module": {
            "id": module.id,
            "name": module.name,
            "slug": module.slug,
        } if module else None,
        "policy": serialize_output_policy(policy) if policy else default_policy_payload(payload),
        "selected_model": serialize_model_config(selected_model),
        "fallback_model": serialize_model_config(fallback_model),
        "orchestration": {
            "quality_tier": policy.quality_tier if policy else payload.get("quality_tier") or "standard",
            "max_output_tokens": policy.max_output_tokens if policy else clamp_int(payload.get("max_output_tokens"), 120, 4000, 600),
            "temperature_x100": policy.temperature_x100 if policy else clamp_int(payload.get("temperature_x100"), 0, 200, 70),
            "response_format": policy.response_format if policy else payload.get("response_format") or "json",
            "safety_rules": policy.safety_rules if policy else payload.get("safety_rules") or "保持安全边界，避免医疗、法律、投资承诺。",
        },
    }


def resolve_output_policy(session: Session, policy_id: int | None) -> OutputPolicy | None:
    statement = select(OutputPolicy).options(joinedload(OutputPolicy.primary_model), joinedload(OutputPolicy.fallback_model))
    if policy_id:
        return session.scalar(statement.where(OutputPolicy.id == policy_id))
    return session.scalar(statement.where(OutputPolicy.is_default.is_(True)).order_by(OutputPolicy.created_at.desc(), OutputPolicy.id.desc()))


def resolve_primary_model(session: Session, policy: OutputPolicy | None, payload: dict) -> ModelConfig | None:
    if policy and policy.primary_model and policy.primary_model.is_active:
        return policy.primary_model
    quality_tier = (payload.get("quality_tier") or (policy.quality_tier if policy else "standard")).strip()
    model = session.scalar(
        select(ModelConfig)
        .where(ModelConfig.is_active.is_(True), ModelConfig.quality_tier == quality_tier)
        .order_by(ModelConfig.input_cost_per_1m.asc(), ModelConfig.output_cost_per_1m.asc())
    )
    if model is not None:
        return model
    return session.scalar(select(ModelConfig).where(ModelConfig.is_active.is_(True)).order_by(ModelConfig.id))


def resolve_fallback_model(session: Session, policy: OutputPolicy | None, selected_model: ModelConfig | None) -> ModelConfig | None:
    if policy and policy.fallback_model and policy.fallback_model.is_active:
        return policy.fallback_model
    statement = select(ModelConfig).where(ModelConfig.is_active.is_(True)).order_by(ModelConfig.output_cost_per_1m.asc(), ModelConfig.id.asc())
    if selected_model is not None:
        statement = statement.where(ModelConfig.id != selected_model.id)
    return session.scalar(statement)


def default_policy_payload(payload: dict) -> dict:
    return {
        "id": None,
        "name": "临时路由策略",
        "quality_tier": payload.get("quality_tier") or "standard",
        "primary_model": None,
        "fallback_model": None,
        "max_output_tokens": clamp_int(payload.get("max_output_tokens"), 120, 4000, 600),
        "temperature_x100": clamp_int(payload.get("temperature_x100"), 0, 200, 70),
        "response_format": payload.get("response_format") or "json",
        "safety_rules": payload.get("safety_rules") or "保持安全边界，避免医疗、法律、投资承诺。",
        "is_default": False,
    }


def nullable_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def clamp_int(value, minimum: int, maximum: int, fallback: int) -> int:
    if value in (None, ""):
        return fallback
    return max(minimum, min(maximum, int(value)))


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
