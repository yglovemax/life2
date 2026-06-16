"""bootstrap current schema

Revision ID: 20260616_0001
Revises:
Create Date: 2026-06-16 21:10:00
"""

from __future__ import annotations

from alembic import op

from app import models  # noqa: F401
from app.db import Base, ensure_sqlite_columns


revision = "20260616_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "sqlite":
        ensure_sqlite_columns()


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
