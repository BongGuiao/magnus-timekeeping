from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NoticeTemplateModel(Base):
    __tablename__ = "notice_templates"
    __table_args__ = (
        CheckConstraint("module IN ('TARDINESS', 'RETURN_TO_WORK')", name="ck_notice_templates_module"),
        Index("uq_notice_templates_active_module", "module", unique=True, postgresql_where=text("is_active")),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    sanitized_html: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class TardinessCaseModel(Base):
    __tablename__ = "tardiness_cases"
    __table_args__ = (
        UniqueConstraint("employee_id", "period_start", name="uq_tardiness_case_employee_period"),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr.employees.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class NoticeModel(Base):
    __tablename__ = "issued_notices"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_issued_notice_case"),
        CheckConstraint(
            "(received_at IS NULL AND due_at IS NULL AND receipt_method IS NULL) OR "
            "(received_at IS NOT NULL AND due_at IS NOT NULL AND receipt_method IS NOT NULL)",
            name="ck_notice_receipt_fields",
        ),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    case_id: Mapped[UUID] = mapped_column(ForeignKey("attendance.tardiness_cases.id"), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr.employees.id"), nullable=False)
    template_id: Mapped[UUID] = mapped_column(ForeignKey("attendance.notice_templates.id"), nullable=False)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False)
    field_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rendered_html: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_method: Mapped[str | None] = mapped_column(String(200))
    receipt_recorded_by: Mapped[UUID | None] = mapped_column(ForeignKey("identity.users.id"))
    receipt_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_text: Mapped[str | None] = mapped_column(Text)
    response_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
