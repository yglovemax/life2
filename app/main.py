from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db import get_session, init_db
from app.platform.runtime import get_rate_limiter
from app.models import AdminUser
from app.seed import ensure_seed_data
from app.services import (
    authenticate_admin_token,
    authenticate_app_token,
    cost_summary,
    append_chat_message,
    cancel_training_run,
    create_chat_session,
    create_issue,
    create_knowledge_source,
    create_app_api_key,
    create_memory_item,
    create_manual_knowledge_entry,
    create_model_provider_key,
    create_module,
    create_or_update_app_user,
    create_output_policy,
    create_training_run,
    chat_reply_sse_events,
    generate_chat_reply,
    get_app_user,
    get_chat_session,
    get_module_detail,
    get_training_run,
    get_user_chart,
    import_github_knowledge_sources,
    list_app_api_keys,
    list_audit_events,
    list_fallback_alerts,
    list_issues,
    list_knowledge_chunks,
    list_knowledge_sources,
    list_call_traces,
    list_models,
    list_model_provider_keys,
    list_module_versions,
    list_modules,
    list_output_policies,
    list_pages,
    list_test_users,
    list_training_runs,
    login_admin,
    metrics,
    publish_module,
    publish_training_run,
    preview_model_route,
    record_audit_event,
    retry_training_run,
    rollback_module,
    render_app_module,
    render_app_page,
    revoke_admin_token,
    revoke_app_api_key,
    revoke_model_provider_key,
    run_batch_tests,
    run_module_test,
    score_call_trace,
    search_knowledge,
    security_status,
    serialize_admin_user,
    save_birth_profile,
    list_user_memories,
    training_queue_status,
    update_module,
    update_output_policy,
    update_issue,
    upsert_memory_summary,
    upload_knowledge_files,
)


def bootstrap() -> None:
    init_db()
    session_gen = get_session()
    session = next(session_gen)
    try:
        ensure_seed_data(session)
    finally:
        session.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    yield


bootstrap()
app = FastAPI(title="Nexa AI API Admin", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def require_app_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_nexa_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    token = x_nexa_api_key or ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    auth = authenticate_app_token(session, token, get_settings().app_api_token)
    if auth is None:
        record_audit_event(
            session,
            event_type="app_auth_failed",
            actor="external_app",
            target_type="app_api",
            target_id=request.url.path,
            severity="warning",
            status="blocked",
            details={"path": request.url.path, "token_prefix": f"{token[:4]}***" if token else ""},
        )
        raise HTTPException(status_code=401, detail="invalid app api token")
    return auth


def bearer_token(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def require_admin_session(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> AdminUser:
    user = authenticate_admin_token(session, bearer_token(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="admin login required")
    return user


def require_app_stream_token(
    request: Request,
    api_key: str | None = None,
    authorization: str | None = Header(default=None),
    x_nexa_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    token = x_nexa_api_key or api_key or ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    auth = authenticate_app_token(session, token, get_settings().app_api_token)
    if auth is None:
        record_audit_event(
            session,
            event_type="app_auth_failed",
            actor="external_app",
            target_type="app_stream",
            target_id=request.url.path,
            severity="warning",
            status="blocked",
            details={"path": request.url.path, "token_prefix": f"{token[:4]}***" if token else ""},
        )
        raise HTTPException(status_code=401, detail="invalid app api token")
    return auth


def app_chat_rate_limit_headers(limit: int, remaining: int, reset_at: float) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(max(limit, 1)),
        "X-RateLimit-Remaining": str(max(remaining, 0)),
        "X-RateLimit-Reset": str(max(int(reset_at), 0)),
    }


def enforce_app_chat_rate_limit(auth: dict, session_id: int, response: Response | None = None) -> dict[str, str]:
    settings = get_settings()
    limiter = get_rate_limiter()
    decision = limiter.check(
        f"app-chat:{auth.get('key_id') or auth.get('name') or 'app'}:session:{session_id}",
        limit=max(settings.app_chat_rate_limit_count, 1),
        window_seconds=max(settings.app_chat_rate_limit_window_seconds, 1),
    )
    headers = app_chat_rate_limit_headers(settings.app_chat_rate_limit_count, decision.remaining, decision.reset_at)
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="app chat rate limit exceeded", headers=headers)
    if response is not None:
        for key, value in headers.items():
            response.headers[key] = value
    return headers


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/admin">')


@app.get("/admin", response_class=FileResponse)
def admin() -> FileResponse:
    return FileResponse(static_dir / "admin.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "nexa-ai-api-admin"}


@app.post("/api/auth/login")
def auth_login(payload: dict, session: Session = Depends(get_session)) -> dict:
    result = login_admin(session, payload)
    if result is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    return result


@app.get("/api/auth/me")
def auth_me(admin_user: AdminUser = Depends(require_admin_session)) -> dict:
    return serialize_admin_user(admin_user)


@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = Header(default=None), session: Session = Depends(get_session)) -> dict:
    revoked = revoke_admin_token(session, bearer_token(authorization))
    return {"ok": revoked}


@app.post("/api/app/modules/{module_slug}/render")
def app_module_render(
    module_slug: str,
    payload: dict,
    app_auth: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    rendered = render_app_module(session, module_slug, payload)
    if rendered is None:
        raise HTTPException(status_code=404, detail="module not found or not published")
    record_audit_event(
        session,
        event_type="app_module_render",
        actor=app_auth["name"],
        target_type="module",
        target_id=module_slug,
        severity="info",
        details={"request_id": rendered["request_id"], "trace_id": rendered["trace_id"]},
    )
    return rendered


@app.post("/api/app/pages/{page_slug}/render")
def app_page_render(
    page_slug: str,
    payload: dict,
    app_auth: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    rendered = render_app_page(session, page_slug, payload)
    if rendered is None:
        raise HTTPException(status_code=404, detail="page not found")
    record_audit_event(
        session,
        event_type="app_page_render",
        actor=app_auth["name"],
        target_type="page",
        target_id=page_slug,
        severity="info",
        details={"request_id": rendered["request_id"], "module_count": rendered["meta"]["module_count"]},
    )
    return rendered


@app.post("/api/app/users")
def app_user_create(
    payload: dict,
    app_auth: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    try:
        user = create_or_update_app_user(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit_event(
        session,
        event_type="app_user_upsert",
        actor=app_auth["name"],
        target_type="app_user",
        target_id=str(user["id"]),
        severity="info",
        details={"external_id": user["external_id"]},
    )
    return user


@app.get("/api/app/users/{user_id}")
def app_user_detail(
    user_id: int,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    user = get_app_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="app user not found")
    return user


@app.put("/api/app/users/{user_id}/birth-profile")
def app_user_birth_profile_save(
    user_id: int,
    payload: dict,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    profile = save_birth_profile(session, user_id, payload)
    if profile is None:
        raise HTTPException(status_code=404, detail="app user not found")
    return profile


@app.get("/api/app/users/{user_id}/chart")
def app_user_chart(
    user_id: int,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    chart = get_user_chart(session, user_id)
    if chart is None:
        raise HTTPException(status_code=404, detail="app user not found")
    return chart


@app.post("/api/app/chat/sessions")
def app_chat_session_create(
    payload: dict,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    chat_session = create_chat_session(session, payload)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="app user not found")
    return chat_session


@app.get("/api/app/chat/sessions/{session_id}")
def app_chat_session_detail(
    session_id: int,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    chat_session = get_chat_session(session, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    return chat_session


@app.post("/api/app/chat/sessions/{session_id}/messages")
def app_chat_session_message_create(
    session_id: int,
    payload: dict,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    try:
        message = append_chat_message(session, session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if message is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    return message


@app.post("/api/app/chat/sessions/{session_id}/reply")
def app_chat_session_reply(
    session_id: int,
    payload: dict,
    response: Response,
    auth: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    enforce_app_chat_rate_limit(auth, session_id, response=response)
    try:
        reply = generate_chat_reply(session, session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if reply is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    return reply


@app.get("/api/app/chat/sessions/{session_id}/stream")
def app_chat_session_stream(
    session_id: int,
    content: str,
    simulate_model_response: str | None = None,
    auth: dict = Depends(require_app_stream_token),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    headers = enforce_app_chat_rate_limit(auth, session_id)
    payload = {"content": content}
    if simulate_model_response is not None:
        payload["simulate_model_response"] = simulate_model_response
    try:
        reply = generate_chat_reply(session, session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if reply is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    return StreamingResponse(chat_reply_sse_events(reply), media_type="text/event-stream", headers=headers)


@app.put("/api/app/users/{user_id}/memory-summary")
def app_user_memory_summary_save(
    user_id: int,
    payload: dict,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    summary = upsert_memory_summary(session, user_id, payload)
    if summary is None:
        raise HTTPException(status_code=404, detail="app user not found")
    return summary


@app.post("/api/app/users/{user_id}/memories")
def app_user_memory_create(
    user_id: int,
    payload: dict,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    try:
        item = create_memory_item(session, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="app user not found")
    return item


@app.get("/api/app/users/{user_id}/memories")
def app_user_memories(
    user_id: int,
    _: dict = Depends(require_app_token),
    session: Session = Depends(get_session),
) -> dict:
    memories = list_user_memories(session, user_id)
    if memories is None:
        raise HTTPException(status_code=404, detail="app user not found")
    return memories


@app.get("/api/modules")
def modules(session: Session = Depends(get_session)) -> dict:
    return {"items": list_modules(session)}


@app.get("/api/pages")
def pages(session: Session = Depends(get_session)) -> dict:
    return {"items": list_pages(session)}


@app.get("/api/models")
def models(session: Session = Depends(get_session)) -> dict:
    return {"items": list_models(session)}


@app.get("/api/test-users")
def test_users() -> dict:
    return {"items": list_test_users()}


@app.get("/api/knowledge-sources")
def knowledge_sources(session: Session = Depends(get_session)) -> dict:
    return {"items": list_knowledge_sources(session)}


@app.post("/api/knowledge-sources")
def knowledge_source_create(payload: dict, session: Session = Depends(get_session)) -> dict:
    return create_knowledge_source(session, payload)


@app.post("/api/knowledge/uploads")
def knowledge_uploads(payload: dict, session: Session = Depends(get_session)) -> dict:
    try:
        return upload_knowledge_files(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/knowledge/github-import")
def knowledge_github_import(payload: dict, session: Session = Depends(get_session)) -> dict:
    try:
        return import_github_knowledge_sources(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/knowledge-entries")
def knowledge_entry_create(payload: dict, session: Session = Depends(get_session)) -> dict:
    return create_manual_knowledge_entry(session, payload)


@app.get("/api/knowledge-chunks")
def knowledge_chunks(tag: str | None = None, source_id: int | None = None, session: Session = Depends(get_session)) -> dict:
    return {"items": list_knowledge_chunks(session, tag=tag, source_id=source_id)}


@app.post("/api/knowledge/search")
def knowledge_search(payload: dict, session: Session = Depends(get_session)) -> dict:
    return {"items": search_knowledge(session, payload)}


@app.get("/api/training/runs")
def training_runs(session: Session = Depends(get_session)) -> dict:
    return {"items": list_training_runs(session)}


@app.get("/api/training/queue-status")
def training_queue_status_view(session: Session = Depends(get_session)) -> dict:
    return training_queue_status(session)


@app.post("/api/training/runs")
def training_run_create(payload: dict, session: Session = Depends(get_session)) -> dict:
    try:
        return create_training_run(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/training/runs/{run_id}")
def training_run_detail(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = get_training_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="training run not found")
    return run


@app.post("/api/training/runs/{run_id}/publish")
def training_run_publish(run_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    try:
        run = publish_training_run(session, run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="training run not found")
    return run


@app.post("/api/training/runs/{run_id}/retry")
def training_run_retry(run_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    try:
        run = retry_training_run(session, run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="training run not found")
    return run


@app.post("/api/training/runs/{run_id}/cancel")
def training_run_cancel(run_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    try:
        run = cancel_training_run(session, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="training run not found")
    return run


@app.post("/api/modules")
def module_create(payload: dict, session: Session = Depends(get_session)) -> dict:
    return create_module(session, payload)


@app.get("/api/modules/{module_id}")
def module_detail(module_id: int, session: Session = Depends(get_session)) -> dict:
    detail = get_module_detail(session, module_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="module not found")
    return detail


@app.put("/api/modules/{module_id}")
def module_update(module_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    detail = update_module(session, module_id, payload)
    if detail is None:
        raise HTTPException(status_code=404, detail="module not found")
    return detail


@app.get("/api/modules/{module_id}/versions")
def module_versions(module_id: int, session: Session = Depends(get_session)) -> dict:
    versions = list_module_versions(session, module_id)
    if versions is None:
        raise HTTPException(status_code=404, detail="module not found")
    return {"items": versions}


@app.post("/api/modules/{module_id}/publish")
def module_publish(module_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    detail = publish_module(session, module_id, payload)
    if detail is None:
        raise HTTPException(status_code=404, detail="module not found")
    return detail


@app.post("/api/modules/{module_id}/rollback")
def module_rollback(module_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    detail = rollback_module(session, module_id, payload)
    if detail is None:
        raise HTTPException(status_code=404, detail="module not found")
    return detail


@app.post("/api/modules/{module_id}/test-run")
def module_test_run(module_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    trace = run_module_test(session, module_id, payload)
    if trace is None:
        raise HTTPException(status_code=404, detail="module not found")
    return trace


@app.post("/api/test-runs/batch")
def batch_test_run(payload: dict, session: Session = Depends(get_session)) -> dict:
    return {"items": run_batch_tests(session, payload)}


@app.get("/api/call-traces")
def call_traces(request_type: str | None = None, session: Session = Depends(get_session)) -> dict:
    return {"items": list_call_traces(session, request_type=request_type)}


@app.put("/api/call-traces/{trace_id}/score")
def call_trace_score(trace_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    trace = score_call_trace(session, trace_id, payload)
    if trace is None:
        raise HTTPException(status_code=404, detail="call trace not found")
    return trace


@app.get("/api/issues")
def issues(status: str | None = None, owner: str | None = None, module_id: int | None = None, session: Session = Depends(get_session)) -> dict:
    return {"items": list_issues(session, status=status, owner=owner, module_id=module_id)}


@app.post("/api/modules/{module_id}/issues")
def module_issue_create(module_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    issue = create_issue(session, module_id, payload)
    if issue is None:
        raise HTTPException(status_code=404, detail="module not found")
    return issue


@app.put("/api/issues/{issue_id}")
def issue_update(issue_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    issue = update_issue(session, issue_id, payload)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue not found")
    return issue


@app.get("/api/model-provider-keys")
def model_provider_keys(_: AdminUser = Depends(require_admin_session), session: Session = Depends(get_session)) -> dict:
    return {"items": list_model_provider_keys(session)}


@app.post("/api/model-provider-keys")
def model_provider_key_create(
    payload: dict,
    admin_user: AdminUser = Depends(require_admin_session),
    session: Session = Depends(get_session),
) -> dict:
    payload = {**payload, "operator": payload.get("operator") or admin_user.username}
    return create_model_provider_key(session, payload)


@app.post("/api/model-provider-keys/{key_id}/revoke")
def model_provider_key_revoke(
    key_id: int,
    payload: dict,
    admin_user: AdminUser = Depends(require_admin_session),
    session: Session = Depends(get_session),
) -> dict:
    payload = {**payload, "operator": payload.get("operator") or admin_user.username}
    key = revoke_model_provider_key(session, key_id, payload)
    if key is None:
        raise HTTPException(status_code=404, detail="model provider key not found")
    return key


@app.get("/api/output-policies")
def output_policies(session: Session = Depends(get_session)) -> dict:
    return {"items": list_output_policies(session)}


@app.post("/api/output-policies")
def output_policy_create(payload: dict, _: AdminUser = Depends(require_admin_session), session: Session = Depends(get_session)) -> dict:
    return create_output_policy(session, payload)


@app.put("/api/output-policies/{policy_id}")
def output_policy_update(policy_id: int, payload: dict, _: AdminUser = Depends(require_admin_session), session: Session = Depends(get_session)) -> dict:
    policy = update_output_policy(session, policy_id, payload)
    if policy is None:
        raise HTTPException(status_code=404, detail="output policy not found")
    return policy


@app.post("/api/model-router/preview")
def model_router_preview(payload: dict, session: Session = Depends(get_session)) -> dict:
    return preview_model_route(session, payload)


@app.get("/api/costs/summary")
def costs_summary(session: Session = Depends(get_session)) -> dict:
    return cost_summary(session)


@app.get("/api/fallback-alerts")
def fallback_alerts(session: Session = Depends(get_session)) -> dict:
    return {"items": list_fallback_alerts(session)}


@app.get("/api/security/status")
def security_status_view(session: Session = Depends(get_session)) -> dict:
    return security_status(session, get_settings().app_api_token)


@app.get("/api/security/app-keys")
def security_app_keys(_: AdminUser = Depends(require_admin_session), session: Session = Depends(get_session)) -> dict:
    return {"items": list_app_api_keys(session)}


@app.post("/api/security/app-keys")
def security_app_key_create(
    payload: dict,
    admin_user: AdminUser = Depends(require_admin_session),
    session: Session = Depends(get_session),
) -> dict:
    payload = {**payload, "operator": payload.get("operator") or admin_user.username}
    return create_app_api_key(session, payload)


@app.post("/api/security/app-keys/{key_id}/revoke")
def security_app_key_revoke(
    key_id: int,
    payload: dict,
    admin_user: AdminUser = Depends(require_admin_session),
    session: Session = Depends(get_session),
) -> dict:
    payload = {**payload, "operator": payload.get("operator") or admin_user.username}
    key = revoke_app_api_key(session, key_id, payload)
    if key is None:
        raise HTTPException(status_code=404, detail="app key not found")
    return key


@app.get("/api/security/audit-events")
def security_audit_events(
    event_type: str | None = None,
    _: AdminUser = Depends(require_admin_session),
    session: Session = Depends(get_session),
) -> dict:
    return {"items": list_audit_events(session, event_type=event_type)}


@app.get("/api/metrics")
def admin_metrics(session: Session = Depends(get_session)) -> dict:
    return metrics(session)
