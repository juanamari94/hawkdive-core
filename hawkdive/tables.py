from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Notification(Base):
    __tablename__ = 'notifications'
    __table_args__ = (UniqueConstraint('source', 'grafana_org_id', 'digest'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    grafana_org_id: Mapped[int]
    digest: Mapped[str] = mapped_column(Text)
    payload: Mapped[str] = mapped_column(Text)


class AlertOccurrence(Base):
    """One firing period. The existing table/API name 'issues' is retained for compatibility."""
    __tablename__ = 'issues'
    __table_args__ = (UniqueConstraint('source', 'grafana_org_id', 'fingerprint', 'starts_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    grafana_org_id: Mapped[int]
    fingerprint: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    alert: Mapped[str] = mapped_column(Text)


class Investigation(Base):
    __tablename__ = 'investigations'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    signature: Mapped[str] = mapped_column(Text, index=True)
    trigger: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    window_ends_at: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint("status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')"),)


class InvestigationOccurrence(Base):
    """Link multiple stored firing periods to one investigation within its eligibility window."""
    __tablename__ = 'investigation_occurrences'
    issue_id: Mapped[int] = mapped_column(ForeignKey('issues.id'), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey('investigations.id'))


class Attempt(Base):
    __tablename__ = 'attempts'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey('investigations.id'))
    number: Mapped[int]
    active_signature: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    execution_reference: Mapped[str | None] = mapped_column(Text)
    exit_code: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint('investigation_id', 'number'),
        CheckConstraint("status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')"),
        Index('one_active_attempt_per_investigation', 'investigation_id', unique=True,
              sqlite_where=text("status IN ('PENDING', 'RUNNING')")),
    )


class InvestigationOutput(Base):
    __tablename__ = 'investigation_outputs'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int]
    __table_args__ = (UniqueConstraint('attempt_id', 'sequence'),)
