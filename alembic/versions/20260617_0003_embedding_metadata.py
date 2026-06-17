"""add embedding metadata columns

Revision ID: 20260617_0003
Revises: 20260617_0002
Create Date: 2026-06-17 10:30:00
"""

from __future__ import annotations

from alembic import op


revision = "20260617_0003"
down_revision = "20260617_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_hash VARCHAR(80) DEFAULT ''")
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_payload JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embedding_hash VARCHAR(80) DEFAULT ''")
    op.execute("ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embedding_payload JSONB DEFAULT '{}'::jsonb")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hash ON knowledge_chunks (embedding_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_memory_items_embedding_hash ON memory_items (embedding_hash)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_memory_items_embedding_hash")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hash")
    op.execute("ALTER TABLE memory_items DROP COLUMN IF EXISTS embedding_payload")
    op.execute("ALTER TABLE memory_items DROP COLUMN IF EXISTS embedding_hash")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_payload")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_hash")
