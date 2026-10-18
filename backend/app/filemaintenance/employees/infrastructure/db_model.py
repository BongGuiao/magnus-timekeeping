from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Float,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmployeeModel(Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("employee_no", name="uq_employees_employee_no"),
        CheckConstraint(
            "record_status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_employees_record_status",
        ),
        {"schema": "hr"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    employee_no: Mapped[str] = mapped_column(String(30), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    suffix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    preferred_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    personal_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mobile_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    photo_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="ACTIVE",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


OPERATIONAL_GROUPS = ("SLI", "SLR", "ASS", "MTT", "COLLECTION", "FLEET", "WAREHOUSE", "OFFICE", "OTHER")


class EmployeeWfhLocationModel(Base):
    __tablename__ = "employee_wfh_locations"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_employee_wfh_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_employee_wfh_longitude"),
        {"schema": "hr"},
    )

    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id", ondelete="CASCADE"), primary_key=True
    )
    geofence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("location.geofences.id"), nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)


class EmploymentAssignmentModel(Base):
    __tablename__ = "employment_assignments"
    __table_args__ = (
        CheckConstraint(
            "operational_group IS NULL OR operational_group IN ("
            + ", ".join(f"'{group}'" for group in OPERATIONAL_GROUPS)
            + ")",
            name="ck_employment_assignments_operational_group",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employment_assignments_effective_dates",
        ),
        UniqueConstraint("id", "company_id", name="uq_employment_assignments_id_company"),
        {"schema": "hr"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    employee_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.companies.id"), nullable=False)
    org_unit_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.org_units.id"), nullable=True)
    # hr.positions and core.locations have no ORM models yet; their FKs are enforced by the database.
    position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    supervisor_employee_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=True
    )
    employment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    employee_category: Mapped[str] = mapped_column(String(30), nullable=False)
    operational_group: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payroll_group_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll.payroll_groups.id", name="fk_assignment_payroll_group"),
        nullable=True,
    )
    primary_location_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    separation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class EmploymentAssignmentGeofenceModel(Base):
    __tablename__ = "employment_assignment_geofences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_id", "company_id"],
            ["hr.employment_assignments.id", "hr.employment_assignments.company_id"],
            ondelete="CASCADE",
            name="fk_assignment_geofences_assignment_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "geofence_id"],
            ["location.geofences.company_id", "location.geofences.id"],
            ondelete="CASCADE",
            name="fk_assignment_geofences_company_geofence",
        ),
        {"schema": "hr"},
    )

    assignment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    geofence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )


class EmploymentAssignmentLocationModel(Base):
    __tablename__ = "employment_assignment_locations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_id", "company_id"],
            ["hr.employment_assignments.id", "hr.employment_assignments.company_id"],
            ondelete="CASCADE",
            name="fk_assignment_locations_assignment_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["core.locations.company_id", "core.locations.id"],
            ondelete="CASCADE",
            name="fk_assignment_locations_company_location",
        ),
        {"schema": "hr"},
    )

    assignment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    location_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)


class EmployeeSkillModel(Base):
    __tablename__ = "employee_skills"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "skill_code",
            "certification_no",
            name="uq_employee_skills_employee_skill_certification",
        ),
        {"schema": "hr"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    employee_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False)
    skill_code: Mapped[str] = mapped_column(String(50), nullable=False)
    proficiency_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    certification_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    verified_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="VALID")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
