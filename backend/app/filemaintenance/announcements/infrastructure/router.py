from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.audit_logging import stamp_audit_fields
from app.core.database import get_db
from app.core.employee_company_scope import get_active_employee_company_ids
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.announcements.infrastructure.db_model import AnnouncementModel

router = APIRouter(prefix="/announcements", tags=["Announcements"])
PH_TIMEZONE = ZoneInfo("Asia/Manila")


class AnnouncementCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    company_id: UUID | None = None
    is_active: bool = True
    effective_from: date = Field(default_factory=lambda: datetime.now(PH_TIMEZONE).date())
    effective_to: date | None = None

    @model_validator(mode="after")
    def validate_effective_dates(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from.")
        return self


class AnnouncementUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    company_id: UUID | None = None
    is_active: bool | None = None
    effective_from: date | None = None
    effective_to: date | None = None

    @field_validator("title", "body", "effective_from", mode="before")
    @classmethod
    def reject_null_required_values(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("This field cannot be null when provided.")
        return value

    @model_validator(mode="after")
    def validate_effective_dates(self):
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to must be on or after effective_from.")
        return self


class AnnouncementSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    body: str
    company_id: UUID | None
    posted_at: datetime
    is_active: bool
    effective_from: date
    effective_to: date | None

    @staticmethod
    def from_model(announcement: AnnouncementModel) -> "AnnouncementSchema":
        return AnnouncementSchema(
            id=announcement.id,
            title=announcement.title,
            body=announcement.body,
            company_id=announcement.company_id,
            posted_at=announcement.created_at,
            is_active=announcement.is_active,
            effective_from=announcement.effective_from,
            effective_to=announcement.effective_to,
        )


def _get_user_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[AnnouncementSchema]],
    status_code=status.HTTP_200_OK,
)
async def list_announcements(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db),
):
    user_id = _get_user_id(claims)
    today = datetime.now(PH_TIMEZONE).date()
    company_ids = await get_active_employee_company_ids(session, user_id, today)
    company_filter = (
        or_(
            AnnouncementModel.company_id.is_(None),
            AnnouncementModel.company_id.in_(company_ids),
        )
        if company_ids
        else AnnouncementModel.company_id.is_(None)
    )
    announcements = await session.scalars(
        select(AnnouncementModel)
        .where(
            AnnouncementModel.is_active.is_(True),
            AnnouncementModel.effective_from <= today,
            or_(AnnouncementModel.effective_to.is_(None), AnnouncementModel.effective_to >= today),
            company_filter,
        )
        .order_by(AnnouncementModel.created_at.desc(), AnnouncementModel.id)
        .limit(20)
    )
    return ResponseEnvelope(
        status="success",
        data=[AnnouncementSchema.from_model(item) for item in announcements],
    )


@router.get(
    "/manage/list",
    response_model=ResponseEnvelope[list[AnnouncementSchema]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("system.manage"))],
)
async def list_announcements_for_management(
    session: AsyncSession = Depends(get_db),
):
    announcements = await session.scalars(
        select(AnnouncementModel)
        .order_by(AnnouncementModel.created_at.desc(), AnnouncementModel.id)
        .limit(1000)
    )
    return ResponseEnvelope(
        status="success",
        data=[AnnouncementSchema.from_model(item) for item in announcements],
    )


@router.post(
    "/create",
    response_model=ResponseEnvelope[AnnouncementSchema],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("system.manage"))],
)
async def create_announcement(
    payload: AnnouncementCreateRequest,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    values = stamp_audit_fields(payload.model_dump(), user_id, creating=True)
    announcement = AnnouncementModel(**values)
    session.add(announcement)
    await session.flush()
    result = AnnouncementSchema.from_model(announcement)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="announcement",
        resource_id=announcement.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[AnnouncementSchema],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("system.manage"))],
)
async def update_announcement(
    payload: AnnouncementUpdateRequest,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    announcement = await session.scalar(
        select(AnnouncementModel).where(AnnouncementModel.id == payload.id)
    )
    if announcement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found.")

    before = AnnouncementSchema.from_model(announcement)
    changes = payload.model_dump(exclude_unset=True, exclude={"id"})
    effective_from = changes.get("effective_from", announcement.effective_from)
    effective_to = changes.get("effective_to", announcement.effective_to)
    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="effective_to must be on or after effective_from.",
        )
    for field, value in changes.items():
        setattr(announcement, field, value)
    announcement.updated_at = datetime.now(PH_TIMEZONE)
    announcement.updated_by = user_id
    announcement.row_version += 1
    await session.flush()
    result = AnnouncementSchema.from_model(announcement)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="announcement",
        resource_id=announcement.id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)
