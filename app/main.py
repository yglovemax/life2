from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db import get_session, init_db
from app.seed import ensure_seed_data
from app.services import (
    authenticate_app_token,
    cost_summary,
    create_knowledge_source,
    create_app_api_key,
    create_manual_knowledge_entry,
    create_module,
    get_module_detail,
    list_app_api_keys,
    list_audit_events,
    list_fallback_alerts,
    list_knowledge_chunks,
    list_knowledge_sources,
    list_call_traces,
    list_models,
    list_module_versions,
    list_modules,
    list_pages,
    list_test_users,
    metrics,
    publish_module,
    record_audit_event,
    rollback_module,
    render_app_module,
    render_app_page,
    revoke_app_api_key,
    run_batch_tests,
    run_module_test,
    score_call_trace,
    search_knowledge,
    security_status,
    update_module,
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


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/admin">')


@app.get("/admin", response_class=FileResponse)
def admin() -> FileResponse:
    return FileResponse(static_dir / "admin.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "nexa-ai-api-admin"}


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


@app.post("/api/knowledge-entries")
def knowledge_entry_create(payload: dict, session: Session = Depends(get_session)) -> dict:
    return create_manual_knowledge_entry(session, payload)


@app.get("/api/knowledge-chunks")
def knowledge_chunks(tag: str | None = None, source_id: int | None = None, session: Session = Depends(get_session)) -> dict:
    return {"items": list_knowledge_chunks(session, tag=tag, source_id=source_id)}


@app.post("/api/knowledge/search")
def knowledge_search(payload: dict, session: Session = Depends(get_session)) -> dict:
    return {"items": search_knowledge(session, payload)}


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
def security_app_keys(session: Session = Depends(get_session)) -> dict:
    return {"items": list_app_api_keys(session)}


@app.post("/api/security/app-keys")
def security_app_key_create(payload: dict, session: Session = Depends(get_session)) -> dict:
    return create_app_api_key(session, payload)


@app.post("/api/security/app-keys/{key_id}/revoke")
def security_app_key_revoke(key_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    key = revoke_app_api_key(session, key_id, payload)
    if key is None:
        raise HTTPException(status_code=404, detail="app key not found")
    return key


@app.get("/api/security/audit-events")
def security_audit_events(event_type: str | None = None, session: Session = Depends(get_session)) -> dict:
    return {"items": list_audit_events(session, event_type=event_type)}


@app.get("/api/metrics")
def admin_metrics(session: Session = Depends(get_session)) -> dict:
    return metrics(session)
