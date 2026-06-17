"""add pgvector embedding columns

Revision ID: 20260617_0002
Revises: 20260616_0001
Create Date: 2026-06-17 10:00:00
"""

from __future__ import annotations

from alembic import op


revision = "20260617_0002"
down_revision = "20260616_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding vector(1536)")
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(120) DEFAULT ''")
    op.execute("ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embedding vector(1536)")
    op.execute("ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(120) DEFAULT ''")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_ivfflat "
        "ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_items_embedding_ivfflat "
        "ON memory_items USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_memory_items_embedding_ivfflat")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_ivfflat")
    op.execute("ALTER TABLE memory_items DROP COLUMN IF EXISTS embedding_model")
    op.execute("ALTER TABLE memory_items DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_model")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding")
