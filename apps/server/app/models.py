"""SQLAlchemy models. Every business table starts with user_id (design P0-1)."""
import datetime as dt
import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    """Local-aware timestamp. v1 treats dates in the user's local timezone
    (design: heatmap/today stats are local-date based), so created_at must
    share that timezone for date-boundary queries to line up."""
    return dt.datetime.now().astimezone()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)  # N2
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    keys: Mapped["UserKeys | None"] = relationship(back_populates="user", uselist=False)


class UserKeys(Base):
    """Per-user encryption credentials (design P0-4, N1)."""
    __tablename__ = "user_keys"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    wrapped_dek: Mapped[str] = mapped_column(Text)          # DEK wrapped by PIN-derived KEK
    kek_salt: Mapped[str] = mapped_column(String(64))
    pin_verify_salt: Mapped[str] = mapped_column(String(64))
    pin_verify_hash: Mapped[str] = mapped_column(String(256))
    admin_wrapped_dek: Mapped[str | None] = mapped_column(Text, nullable=True)  # recovery wrap
    admin_kek_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="keys")


class EntryCategory(str, enum.Enum):
    work = "work"
    routine = "routine"
    diet = "diet"
    study = "study"
    exercise = "exercise"
    social = "social"


class Entry(Base):
    """Journal entries. Private records keep plaintext columns NULL (clarify-3)."""
    __tablename__ = "entries"
    __table_args__ = (
        Index("ix_entries_user_created", "user_id", "created_at"),
        Index("ix_entries_user_primary", "user_id", "primary_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    categories: Mapped[list] = mapped_column(JSON, default=list)          # P0-2 multi
    primary_category: Mapped[EntryCategory] = mapped_column(Enum(EntryCategory))
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)  # relative paths
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_blob: Mapped[str | None] = mapped_column(Text, nullable=True)  # AES-GCM payload
    extra_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_allowed: Mapped[bool] = mapped_column(Boolean, default=True)        # per-entry AI opt-in
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PrivacySetting(Base):
    __tablename__ = "privacy_settings"
    __table_args__ = (Index("ix_privacy_user_cat", "user_id", "category", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[EntryCategory] = mapped_column(Enum(EntryCategory))
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    pin_required: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = default rule


class GoalStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    done = "done"
    abandoned = "abandoned"


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (Index("ix_goals_user", "user_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dimension: Mapped[str | None] = mapped_column(String(32), nullable=True)  # health/finance/...
    deadline: Mapped[dt.date | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[GoalStatus] = mapped_column(Enum(GoalStatus), default=GoalStatus.active)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="goal")


class Granularity(str, enum.Enum):
    year = "year"
    month = "month"
    week = "week"


class TaskStatus(str, enum.Enum):
    backlog = "backlog"
    doing = "doing"
    done = "done"


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_status", "user_id", "status"),
        Index("ix_tasks_parent", "parent_task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), nullable=True)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    granularity: Mapped[Granularity] = mapped_column(Enum(Granularity))
    title: Mapped[str] = mapped_column(String(256))
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 high .. 3 low
    estimate_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.backlog)
    order: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    goal: Mapped[Goal | None] = relationship(back_populates="tasks")
    actions: Mapped[list["Action"]] = relationship(back_populates="task")


class ActionStatus(str, enum.Enum):
    open = "open"
    done = "done"
    debt = "debt"       # postponed >= 3 times (P0-6)
    given_up = "given_up"


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (Index("ix_actions_user_date", "user_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(256))
    minutes: Mapped[int] = mapped_column(Integer, default=30)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    status: Mapped[ActionStatus] = mapped_column(Enum(ActionStatus), default=ActionStatus.open)
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    postpone_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    task: Mapped[Task | None] = relationship(back_populates="actions")


class Projection(Base):
    __tablename__ = "projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    input_snapshot_json: Mapped[dict] = mapped_column(JSON)   # macro/industry/health params
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    report_md: Mapped[str] = mapped_column(Text)
    suggestions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)  # persisted goal suggestions


class LLMCache(Base):
    __tablename__ = "llm_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    response: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Report(Base):
    """Editable AI-generated periodic reports: week/month/year (timeline feature)."""
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_user_period", "user_id", "period_type", "period_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period_type: Mapped[str] = mapped_column(String(10))   # week | month | year
    period_key: Mapped[str] = mapped_column(String(16))    # e.g. 2026-W42 / 2026-10 / 2026
    content_md: Mapped[str] = mapped_column(Text)          # user-editable markdown
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)  # False after manual edit
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class KnowledgeDomain(Base):
    """个人知识库:领域(顶层分组)."""
    __tablename__ = "knowledge_domains"
    __table_args__ = (Index("ix_kdomain_user", "user_id", "name", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeFolder(Base):
    """个人知识库:文件夹,属于某个领域."""
    __tablename__ = "knowledge_folders"
    __table_args__ = (Index("ix_kfolder_user_domain", "user_id", "domain_id", "name", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("knowledge_domains.id"))
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeNote(Base):
    """个人知识库:Markdown 笔记,属于某个文件夹."""
    __tablename__ = "knowledge_notes"
    __table_args__ = (Index("ix_knote_user_folder", "user_id", "folder_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("knowledge_folders.id"))
    title: Mapped[str] = mapped_column(String(256))
    content_md: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AutoPlanLog(Base):
    """Marks that today's auto-plan ran for a user (02:00 scheduler + lazy catch-up)."""
    __tablename__ = "auto_plan_logs"
    __table_args__ = (
        Index("ix_autoplan_user_date", "user_id", "plan_date", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_date: Mapped[dt.date] = mapped_column(Date)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailySummary(Base):
    """Persisted daily summaries (editable); 01:00 job generates for previous day."""
    __tablename__ = "daily_summaries"
    __table_args__ = (
        Index("ix_summary_user_date", "user_id", "summary_date", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    summary_date: Mapped[dt.date] = mapped_column(Date)
    content_md: Mapped[str] = mapped_column(Text)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
