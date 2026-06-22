"""add algorithm registry tables

Revision ID: 20260622_0004
Revises: 20260617_0003
Create Date: 2026-06-22 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "20260622_0004"
down_revision = "20260617_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "algorithm_definitions" not in table_names:
        op.create_table(
            "algorithm_definitions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=180), nullable=False),
            sa.Column("domain", sa.String(length=80), nullable=False),
            sa.Column("algorithm_type", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("current_version_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_algorithm_definitions_slug", "algorithm_definitions", ["slug"], unique=True)
        op.create_index("ix_algorithm_definitions_domain", "algorithm_definitions", ["domain"], unique=False)
        op.create_index("ix_algorithm_definitions_algorithm_type", "algorithm_definitions", ["algorithm_type"], unique=False)
        op.create_index("ix_algorithm_definitions_status", "algorithm_definitions", ["status"], unique=False)

    if "algorithm_versions" not in table_names:
        op.create_table(
            "algorithm_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("algorithm_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("spec", sa.JSON(), nullable=False),
            sa.Column("input_schema", sa.JSON(), nullable=False),
            sa.Column("output_schema", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("created_by", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["algorithm_id"], ["algorithm_definitions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_algorithm_versions_algorithm_id", "algorithm_versions", ["algorithm_id"], unique=False)
        op.create_index("ix_algorithm_versions_status", "algorithm_versions", ["status"], unique=False)

    if "algorithm_runs" not in table_names:
        op.create_table(
            "algorithm_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("algorithm_id", sa.Integer(), nullable=False),
            sa.Column("version_id", sa.Integer(), nullable=True),
            sa.Column("run_mode", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("input_payload", sa.JSON(), nullable=False),
            sa.Column("output_payload", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("created_by", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["algorithm_id"], ["algorithm_definitions.id"]),
            sa.ForeignKeyConstraint(["version_id"], ["algorithm_versions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_algorithm_runs_algorithm_id", "algorithm_runs", ["algorithm_id"], unique=False)
        op.create_index("ix_algorithm_runs_version_id", "algorithm_runs", ["version_id"], unique=False)
        op.create_index("ix_algorithm_runs_run_mode", "algorithm_runs", ["run_mode"], unique=False)
        op.create_index("ix_algorithm_runs_status", "algorithm_runs", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "algorithm_runs" in table_names:
        op.drop_table("algorithm_runs")
    if "algorithm_versions" in table_names:
        op.drop_table("algorithm_versions")
    if "algorithm_definitions" in table_names:
        op.drop_table("algorithm_definitions")
