from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AbsenceStreakAlertModel(Base):
    __tablename__ = "absence_streak_alerts"
    __table_args__ = (
        UniqueConstraint("employee_id", "first_absence_date", name="uq_absence_streak_employee_start"),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr.employees.id"), nullable=False)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("core.companies.id"), nullable=False)
    first_absence_date: Mapped[date] = mapped_column(Date, nullable=False)
    second_absence_date: Mapped[date] = mapped_column(Date, nullable=False)
    third_absence_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AbsenceStreakDismissalModel(Base):
    __tablename__ = "absence_streak_dismissals"
    __table_args__ = {"schema": "attendance"}

    alert_id: Mapped[UUID] = mapped_column(ForeignKey("attendance.absence_streak_alerts.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), primary_key=True)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
