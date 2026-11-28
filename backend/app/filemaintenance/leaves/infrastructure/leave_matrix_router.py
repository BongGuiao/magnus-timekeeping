from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.auth.infrastructure.db_model import RoleModel, UserModel
from app.core.employee_company_scope import get_latest_active_employee_company_id
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.leaves.infrastructure.db_model import LeaveMatrixModel
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel


class LeaveMatrixRange(BaseModel):
    worked_from: Decimal = Field(ge=0, le=999, decimal_places=2)
    worked_to: Decimal = Field(ge=0, le=999, decimal_places=2)
    leave_hours: Decimal = Field(ge=0, le=8, decimal_places=2)
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def check_range(self):
        if self.worked_from > self.worked_to:
            raise ValueError("Worked hours from must not exceed worked hours to.")
        return self


class LeaveMatrixInput(BaseModel):
    row_version: int = Field(ge=0)
    ranges: list[LeaveMatrixRange] = Field(max_length=100)
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def check_overlaps(self):
        ordered = sorted(self.ranges, key=lambda row: row.worked_from)
        if any(left.worked_to >= right.worked_from for left, right in zip(ordered, ordered[1:])):
            raise ValueError("Worked-hour ranges cannot overlap; both endpoints are inclusive.")
        return self


class LeaveMatrixResponse(BaseModel):
    company_id: UUID
    row_version: int
    ranges: list[LeaveMatrixRange]


class MatrixCompany(BaseModel):
    id: UUID
    company_code: str
    legal_name: str
    model_config = ConfigDict(from_attributes=True)


router = APIRouter(
    prefix="/leave-computation-matrices",
    tags=["Leave Computation Matrices"],
    dependencies=[Depends(require_permission("leave.manage"))],
)


def _actor_id(claims: dict[str, Any]) -> UUID:
    if not claims.get("email"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email claim missing from authentication token.")
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User id claim missing or invalid.") from error


async def _authorized_companies(session: AsyncSession, actor_id: UUID) -> list[CompanyModel]:
    today = datetime.now(ZoneInfo("Asia/Manila")).date()
    result = await session.scalars(
        select(CompanyModel)
        .join(UserRoleModel, or_(UserRoleModel.company_id == CompanyModel.id, UserRoleModel.company_id.is_(None)))
        .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
        .join(UserModel, UserModel.id == UserRoleModel.user_id)
        .join(RolePermissionModel, RolePermissionModel.role_id == RoleModel.id)
        .join(PermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
        .where(
            UserModel.id == actor_id,
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            UserRoleModel.org_unit_id.is_(None),
            UserRoleModel.effective_from <= today,
            or_(UserRoleModel.effective_to.is_(None), UserRoleModel.effective_to >= today),
            RoleModel.is_active.is_(True),
            RolePermissionModel.allowed.is_(True),
            PermissionModel.is_active.is_(True),
            PermissionModel.permission_code == "leave.manage",
        )
        .distinct().order_by(CompanyModel.company_code)
    )
    return list(result.all())


@router.get("/companies", response_model=ResponseEnvelope[list[MatrixCompany]])
async def list_companies(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor_id = _actor_id(claims)
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        company_id = await get_latest_active_employee_company_id(
            uow.session, actor_id, datetime.now(ZoneInfo("Asia/Manila")).date(),
        )
        if company_id is None:
            raise HTTPException(status_code=403, detail="No active employee company assignment was found. Contact HR.")
        company = next(
            (company for company in await _authorized_companies(uow.session, actor_id) if company.id == company_id),
            None,
        )
        if company is None:
            raise HTTPException(status_code=403, detail="You do not have leave management access for your assigned company.")
        result = MatrixCompany.model_validate(company)
    return ResponseEnvelope(status="success", data=[result])


@router.get("/{company_id}", response_model=ResponseEnvelope[LeaveMatrixResponse])
async def get_matrix(
    company_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor_id = _actor_id(claims)
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        if not any(company.id == company_id for company in await _authorized_companies(uow.session, actor_id)):
            raise HTTPException(status_code=403, detail="You cannot manage this company's leave matrix.")
        matrix = await uow.session.get(LeaveMatrixModel, company_id)
        result = LeaveMatrixResponse(
            company_id=company_id, row_version=matrix.row_version if matrix else 0,
            ranges=matrix.ranges if matrix else [],
        )
    return ResponseEnvelope(status="success", data=result)


@router.put("/{company_id}", response_model=ResponseEnvelope[LeaveMatrixResponse])
async def save_matrix(
    company_id: UUID,
    payload: LeaveMatrixInput,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        if not any(company.id == company_id for company in await _authorized_companies(uow.session, actor_id)):
            raise HTTPException(status_code=403, detail="You cannot manage this company's leave matrix.")
        company = await uow.session.scalar(select(CompanyModel).where(CompanyModel.id == company_id).with_for_update())
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found.")
        matrix = await uow.session.get(LeaveMatrixModel, company_id)
        version = matrix.row_version if matrix else 0
        if payload.row_version != version:
            raise HTTPException(status_code=409, detail="This matrix changed. Reload it before saving.")
        before = {"ranges": matrix.ranges, "row_version": version} if matrix else None
        rows = [item.model_dump(mode="json") for item in sorted(payload.ranges, key=lambda row: row.worked_from)]
        if matrix is None:
            matrix = LeaveMatrixModel(company_id=company_id, ranges=rows, row_version=1)
            uow.session.add(matrix)
        else:
            matrix.ranges = rows
            matrix.row_version += 1
        result = LeaveMatrixResponse(company_id=company_id, row_version=matrix.row_version, ranges=rows)
    await log_entity_action(
        es_client, user_id=actor_id, action="UPDATE", resource="leave_computation_matrix",
        resource_id=company_id, before=before, after=result,
    )
    return ResponseEnvelope(status="success", data=result)
