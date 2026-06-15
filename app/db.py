from collections.abc import Generator
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
sqlite_path = settings.sqlite_path
if sqlite_path is not None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_sqlite_columns()


def ensure_sqlite_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "call_traces" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("call_traces")}
    statements = []
    if "manual_score" not in existing:
        statements.append("ALTER TABLE call_traces ADD COLUMN manual_score INTEGER")
    if "reviewer_notes" not in existing:
        statements.append("ALTER TABLE call_traces ADD COLUMN reviewer_notes TEXT DEFAULT ''")
    if "knowledge_hits" not in existing:
        statements.append("ALTER TABLE call_traces ADD COLUMN knowledge_hits JSON DEFAULT '[]'")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
