from collections.abc import Generator
from functools import lru_cache
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    settings = get_settings()
    sqlite_path = settings.sqlite_path
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


@lru_cache
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def reset_db_runtime() -> None:
    get_session_factory.cache_clear()
    get_engine.cache_clear()


def database_runtime_status(check_connection: bool = True) -> dict:
    settings = get_settings()
    url = make_url(settings.database_url)
    backend = url.get_backend_name()
    normalized_backend = "postgresql" if backend.startswith("postgresql") else backend
    pgvector_planned = normalized_backend == "postgresql"
    status = {
        "database": {
            "backend": normalized_backend,
            "driver": url.get_driver_name() or "",
            "safe_url": url.render_as_string(hide_password=True),
            "connected": None,
            "error": "",
        },
        "pgvector": {
            "planned": pgvector_planned,
            "extension": "vector",
            "installed": None,
            "ready": False,
            "dimensions": settings.embedding_dimensions,
            "embedding_model": settings.embedding_model,
            "target_tables": ["knowledge_chunks", "memory_items"],
            "index_type": "ivfflat_cosine",
        },
    }
    if not check_connection:
        return status

    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            status["database"]["connected"] = True
            if pgvector_planned:
                installed = bool(
                    connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar()
                )
                status["pgvector"]["installed"] = installed
                status["pgvector"]["ready"] = installed
    except Exception as exc:  # pragma: no cover - environment-specific diagnostics
        status["database"]["connected"] = False
        status["database"]["error"] = str(exc)[:300]
    return status


def get_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from app import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_columns()


def ensure_sqlite_columns() -> None:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        return
    engine = get_engine()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "call_traces" in table_names:
        existing = {column["name"] for column in inspector.get_columns("call_traces")}
    else:
        existing = set()
    statements = []
    if "manual_score" not in existing:
        statements.append("ALTER TABLE call_traces ADD COLUMN manual_score INTEGER")
    if "reviewer_notes" not in existing:
        statements.append("ALTER TABLE call_traces ADD COLUMN reviewer_notes TEXT DEFAULT ''")
    if "knowledge_hits" not in existing:
        statements.append("ALTER TABLE call_traces ADD COLUMN knowledge_hits JSON DEFAULT '[]'")
    if "training_runs" in table_names:
        training_existing = {column["name"] for column in inspector.get_columns("training_runs")}
        if "run_mode" not in training_existing:
            statements.append("ALTER TABLE training_runs ADD COLUMN run_mode TEXT DEFAULT 'sync'")
        if "task_id" not in training_existing:
            statements.append("ALTER TABLE training_runs ADD COLUMN task_id TEXT DEFAULT ''")
        if "request_payload" not in training_existing:
            statements.append("ALTER TABLE training_runs ADD COLUMN request_payload JSON DEFAULT '{}'")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
