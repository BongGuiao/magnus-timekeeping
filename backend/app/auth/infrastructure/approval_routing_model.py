from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApprovalRouteModel(Base):
    __tablename__ = "approval_routes"
    __table_args__ = (
        CheckConstraint(
            "routing_mode IN ('LEGACY', 'ORG_UNIT', 'UNRESOLVED')",
            name="ck_approval_routes_mode",
        ),
        CheckConstraint(
            "(routing_mode = 'ORG_UNIT' AND approver_employee_id IS NOT NULL) OR "
            "(routing_mode IN ('LEGACY', 'UNRESOLVED') AND approver_employee_id IS NULL)",
            name="ck_approval_routes_approver",
        ),
        CheckConstraint(
            "routing_mode <> 'UNRESOLVED' OR (employee_id IS NOT NULL AND routing_error IS NOT NULL)",
            name="ck_approval_routes_unresolved",
        ),
        Index(
            "uq_approval_routes_current",
            "resource_type",
            "resource_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index(
            "ix_approval_routes_approver",
            "approver_employee_id",
            "resource_type",
            postgresql_where=text("is_current AND routing_mode = 'ORG_UNIT'"),
        ),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    routing_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    employee_id: Mapped[UUID | None] = mapped_column(ForeignKey("hr.employees.id"), nullable=True)
    source_org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("core.org_units.id"), nullable=True)
    approver_org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("core.org_units.id"), nullable=True)
    approver_employee_id: Mapped[UUID | None] = mapped_column(ForeignKey("hr.employees.id"), nullable=True)
    assigned_by: Mapped[UUID | None] = mapped_column(ForeignKey("identity.users.id"), nullable=True)
    routing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
