from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.db import get_session, init_db
from app.seed import ensure_seed_data
from app.services import get_module_detail, list_modules, metrics, run_module_test


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


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/admin">')


@app.get("/admin", response_class=FileResponse)
def admin() -> FileResponse:
    return FileResponse(static_dir / "admin.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "nexa-ai-api-admin"}


@app.get("/api/modules")
def modules(session: Session = Depends(get_session)) -> dict:
    return {"items": list_modules(session)}


@app.get("/api/modules/{module_id}")
def module_detail(module_id: int, session: Session = Depends(get_session)) -> dict:
    detail = get_module_detail(session, module_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="module not found")
    return detail


@app.post("/api/modules/{module_id}/test-run")
def module_test_run(module_id: int, payload: dict, session: Session = Depends(get_session)) -> dict:
    trace = run_module_test(session, module_id, payload)
    if trace is None:
        raise HTTPException(status_code=404, detail="module not found")
    return trace


@app.get("/api/metrics")
def admin_metrics(session: Session = Depends(get_session)) -> dict:
    return metrics(session)
