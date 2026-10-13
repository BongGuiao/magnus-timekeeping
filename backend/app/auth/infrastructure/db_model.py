from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "identity"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    employee_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), unique=True, nullable=True
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(200), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    account_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'PENDING'"))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    created_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class RoleModel(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "identity"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    role_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_system_role: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    created_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
