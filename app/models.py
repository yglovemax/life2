from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ModuleStatus(str, Enum):
    draft = "draft"
    pending_test = "pending_test"
    test_passed = "test_passed"
    pending_approval = "pending_approval"
    gray = "gray"
    live = "live"
    rolled_back = "rolled_back"
    disabled = "disabled"


class IssueStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


class AppKeyStatus(str, Enum):
    active = "active"
    revoked = "revoked"


class AdminSessionStatus(str, Enum):
    active = "active"
    revoked = "revoked"


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    modules: Mapped[list[Module]] = relationship(back_populates="page", cascade="all, delete-orphan")


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), default="openai")
    name: Mapped[str] = mapped_column(String(120), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    quality_tier: Mapped[str] = mapped_column(String(40), default="standard")
    input_cost_per_1m: Mapped[int] = mapped_column(Integer, default=0)
    output_cost_per_1m: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    modules: Mapped[list[Module]] = relationship(back_populates="model")


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"), index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("model_configs.id"), nullable=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    owner: Mapped[str] = mapped_column(String(80), default="未分配")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default=ModuleStatus.draft.value)
    fallback_content: Mapped[str] = mapped_column(Text, default="")
    algorithm_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    knowledge_tags: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    page: Mapped[Page] = relationship(back_populates="modules")
    model: Mapped[ModelConfig | None] = relationship(back_populates="modules")
    prompt: Mapped[PromptTemplate | None] = relationship(back_populates="module", cascade="all, delete-orphan")
    fields: Mapped[list[FieldContract]] = relationship(back_populates="module", cascade="all, delete-orphan")
    calls: Mapped[list[CallTrace]] = relationship(back_populates="module", cascade="all, delete-orphan")
    versions: Mapped[list[ModuleVersion]] = relationship(back_populates="module", cascade="all, delete-orphan")
    issues: Mapped[list[Issue]] = relationship(back_populates="module", cascade="all, delete-orphan")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), unique=True)
    shared_prefix: Mapped[str] = mapped_column(Text, default="")
    module_rules: Mapped[str] = mapped_column(Text, default="")
    algorithm_data_template: Mapped[str] = mapped_column(Text, default="")
    user_preferences_template: Mapped[str] = mapped_column(Text, default="")
    final_request_template: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    module: Mapped[Module] = relationship(back_populates="prompt")


class FieldContract(Base):
    __tablename__ = "field_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(Text, default="")
    display_position: Mapped[str] = mapped_column(String(160), default="")
    example: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(80), default="ai")
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    owner: Mapped[str] = mapped_column(String(80), default="未分配")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    change_log: Mapped[str] = mapped_column(Text, default="")

    module: Mapped[Module] = relationship(back_populates="fields")


class CallTrace(Base):
    __tablename__ = "call_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    request_type: Mapped[str] = mapped_column(String(40), default="test")
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    model_request: Mapped[str] = mapped_column(Text, default="")
    model_raw_response: Mapped[str] = mapped_column(Text, default="")
    final_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="ok")
    fallback_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[str] = mapped_column(String(160), default="")
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    model_name: Mapped[str] = mapped_column(String(120), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    manual_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer_notes: Mapped[str] = mapped_column(Text, default="")
    knowledge_hits: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    module: Mapped[Module] = relationship(back_populates="calls")


class ModuleVersion(Base):
    __tablename__ = "module_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default=ModuleStatus.draft.value)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    module: Mapped[Module] = relationship(back_populates="versions")


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    issue_type: Mapped[str] = mapped_column(String(80))
    owner: Mapped[str] = mapped_column(String(80), default="未分配")
    status: Mapped[str] = mapped_column(String(40), default=IssueStatus.open.value)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    module: Mapped[Module] = relationship(back_populates="issues")


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    source_type: Mapped[str] = mapped_column(String(40), default="markdown")
    status: Mapped[str] = mapped_column(String(40), default="active")
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    chunks: Mapped[list[KnowledgeChunk]] = relationship(back_populates="source", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("knowledge_sources.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    source: Mapped[KnowledgeSource] = relationship(back_populates="chunks")


class AppApiKey(Base):
    __tablename__ = "app_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(40), default=AppKeyStatus.active.value)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(80), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(160), default="system")
    target_type: Mapped[str] = mapped_column(String(80), default="")
    target_id: Mapped[str] = mapped_column(String(120), default="")
    severity: Mapped[str] = mapped_column(String(40), default="info")
    status: Mapped[str] = mapped_column(String(40), default="ok")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(240))
    role: Mapped[str] = mapped_column(String(40), default="owner")
    status: Mapped[str] = mapped_column(String(40), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default=AdminSessionStatus.active.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
