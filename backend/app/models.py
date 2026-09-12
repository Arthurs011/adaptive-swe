"""SQLAlchemy ORM models matching the research schema."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class URNBase(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(URNBase):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    repositories: Mapped[list["Repository"]] = relationship(back_populates="project")


class Repository(URNBase):
    __tablename__ = "repositories"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    url: Mapped[str] = mapped_column(String(1024))
    local_path: Mapped[str] = mapped_column(String(2048))
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    language: Mapped[str] = mapped_column(String(32), default="python")
    commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    graph_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="repositories")
    graph: Mapped["RepositoryGraph | None"] = relationship(
        back_populates="repository", uselist=False
    )
    issues: Mapped[list["Issue"]] = relationship(back_populates="repository")


class RepositoryGraph(URNBase):
    __tablename__ = "repository_graphs"

    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    graph_ml_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    statistics: Mapped[dict] = mapped_column(JSON, default=dict)

    repository: Mapped[Repository] = relationship(back_populates="graph")


class Issue(URNBase):
    __tablename__ = "issues"

    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    title: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="manual")  # manual|github|benchmark
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="issues")
    sessions: Mapped[list["RepairSession"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan"
    )


class RepairStatus(str, enum.Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    GRAPHING = "graphing"
    LOCALIZING = "localizing"
    REPAIRING = "repairing"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RepairSession(URNBase):
    __tablename__ = "repair_sessions"

    issue_id: Mapped[str | None] = mapped_column(ForeignKey("issues.id"), nullable=True)
    repository_id: Mapped[str | None] = mapped_column(ForeignKey("repositories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[RepairStatus] = mapped_column(
        Enum(RepairStatus, name="repair_status"), default=RepairStatus.PENDING
    )
    use_memory: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline: Mapped[str] = mapped_column(String(64), default="proposed")  # baseline1|baseline2|proposed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Summary captured after a run
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    issue: Mapped[Issue] = relationship(back_populates="sessions")
    repository: Mapped[Repository] = relationship()
    attempts: Mapped[list["RepairAttempt"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    timeline_events: Mapped[list["TimelineEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class TimelineEvent(URNBase):
    __tablename__ = "timeline_events"

    session_id: Mapped[str] = mapped_column(ForeignKey("repair_sessions.id"))
    step: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[RepairSession] = relationship(back_populates="timeline_events")


class RepairAttempt(URNBase):
    __tablename__ = "repair_attempts"

    session_id: Mapped[str] = mapped_column(ForeignKey("repair_sessions.id"))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    strategy_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    regression_test_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_test_count: Mapped[int] = mapped_column(Integer, default=0)
    regression_passed: Mapped[int] = mapped_column(Integer, default=0)
    existing_passed: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[RepairSession] = relationship(back_populates="attempts")
    patches: Mapped[list["Patch"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")
    tests: Mapped[list["TestFile"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")
    test_results: Mapped[list["TestResult"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class Patch(URNBase):
    __tablename__ = "patches"

    attempt_id: Mapped[str] = mapped_column(ForeignKey("repair_attempts.id"))
    content: Mapped[str] = mapped_column(Text)  # unified diff
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_files: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempt: Mapped[RepairAttempt] = relationship(back_populates="patches")


class TestFile(URNBase):
    __tablename__ = "tests"

    attempt_id: Mapped[str] = mapped_column(ForeignKey("repair_attempts.id"))
    path: Mapped[str] = mapped_column(String(2048))
    content: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="regression")  # regression|existing

    attempt: Mapped[RepairAttempt] = relationship(back_populates="tests")


class TestResult(URNBase):
    __tablename__ = "test_results"

    attempt_id: Mapped[str] = mapped_column(ForeignKey("repair_attempts.id"))
    test_name: Mapped[str] = mapped_column(String(1024))
    outcome: Mapped[str] = mapped_column(String(32))  # passed|failed|error|skipped
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="regression")  # regression|existing

    attempt: Mapped[RepairAttempt] = relationship(back_populates="test_results")


class RepairMemoryEntry(URNBase):
    __tablename__ = "repair_memory"

    repository_url: Mapped[str] = mapped_column(String(1024))
    issue_description: Mapped[str] = mapped_column(Text)
    issue_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    affected_files: Mapped[list] = mapped_column(JSON, default=list)
    affected_functions: Mapped[list] = mapped_column(JSON, default=list)
    fault_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_patch: Mapped[str] = mapped_column(Text)
    generated_tests: Mapped[list] = mapped_column(JSON, default=list)
    test_results: Mapped[dict] = mapped_column(JSON, default=dict)
    num_attempts: Mapped[int] = mapped_column(Integer, default=1)
    successful: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_reasons: Mapped[list] = mapped_column(JSON, default=list)
    solution_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("repair_sessions.id"), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


class EvaluationRun(URNBase):
    __tablename__ = "evaluation_runs"

    name: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline: Mapped[str] = mapped_column(String(64), default="proposed")
    use_memory: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    items: Mapped[list] = mapped_column(JSON, default=list)

    results: Mapped[list["EvaluationResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvaluationResult(URNBase):
    __tablename__ = "evaluation_results"

    evaluation_run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id"))
    issue_key: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("repair_sessions.id"), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    regression_failures: Mapped[int] = mapped_column(Integer, default=0)
    fault_localization_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[EvaluationRun] = relationship(back_populates="results")


class RepairJob(URNBase):
    """Long-running job handle for the API / frontend."""
    __tablename__ = "repair_jobs"

    session_id: Mapped[str] = mapped_column(ForeignKey("repair_sessions.id"))
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)