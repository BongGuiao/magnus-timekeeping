from datetime import datetime
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text, update

from app.attendance.domain.notice_content import MAX_TEMPLATE_BYTES, NoticeTemplateModule, sanitize_template
from app.attendance.infrastructure.notice_models import NoticeTemplateModel
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work

router = APIRouter(prefix="/notice-templates", tags=["Notice Templates"])
ACTIVATION_LOCK_KEY = "notice-template-activation"


class TemplateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    module: str
    is_active: bool
    created_by: UUID
    created_at: datetime


class TemplateDetail(TemplateSummary):
    sanitized_html: str


async def require_hr_template_manager(
    claims: dict = Depends(get_current_user_claims),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
) -> UUID:
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid user identity.") from error
    authorization = await authorization_use_case.execute(actor_id)
    if not any(role.strip().upper() == "HR_ADMIN" for role in authorization.role_codes):
        raise HTTPException(status_code=403, detail="Only HR administrators can manage notice templates.")
    return actor_id


@router.get("", response_model=ResponseEnvelope[list[TemplateSummary]])
async def list_templates(
    response: Response,
    actor_id: UUID = Depends(require_hr_template_manager),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        rows = (await active.session.execute(
            select(
                NoticeTemplateModel.id, NoticeTemplateModel.name, NoticeTemplateModel.module,
                NoticeTemplateModel.is_active, NoticeTemplateModel.created_by, NoticeTemplateModel.created_at,
            ).order_by(NoticeTemplateModel.created_at.desc(), NoticeTemplateModel.id.desc())
        )).all()
        templates = [TemplateSummary.model_validate(row) for row in rows]
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(status="success", data=templates)


@router.get("/{template_id}", response_model=ResponseEnvelope[TemplateDetail])
async def get_template(
    template_id: UUID,
    response: Response,
    actor_id: UUID = Depends(require_hr_template_manager),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        row = await active.session.get(NoticeTemplateModel, template_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Notice template not found.")
        template = TemplateDetail.model_validate(row)
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(status="success", data=template)


@router.post("", response_model=ResponseEnvelope[TemplateDetail], status_code=201)
async def upload_template(
    response: Response,
    name: str = Form(..., max_length=200),
    module: NoticeTemplateModule = Form(...),
    file: UploadFile = File(...),
    actor_id: UUID = Depends(require_hr_template_manager),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A template name is required.")
    if not file.filename or not file.filename.lower().endswith((".html", ".htm")):
        raise HTTPException(status_code=422, detail="Upload an HTML file with a .html or .htm extension.")
    contents = await file.read(MAX_TEMPLATE_BYTES + 1)
    if len(contents) > MAX_TEMPLATE_BYTES:
        raise HTTPException(status_code=413, detail="The HTML template exceeds 100,000 bytes.")
    try:
        source = contents.decode("utf-8-sig")
        sanitized = sanitize_template(source, module)
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        row = NoticeTemplateModel(name=name, module=module, sanitized_html=sanitized, created_by=actor_id)
        active.session.add(row)
        await active.session.flush()
        await active.session.refresh(row)
        template = TemplateDetail.model_validate(row)
    await log_entity_action(
        es_client, user_id=actor_id, action="CREATE", resource="notice_template", resource_id=template.id,
        after={"name": template.name, "module": template.module},
    )
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(status="success", data=template)


@router.post("/{template_id}/activate", response_model=ResponseEnvelope[TemplateDetail])
async def activate_template(
    template_id: UUID,
    response: Response,
    actor_id: UUID = Depends(require_hr_template_manager),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        session = active.session
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": ACTIVATION_LOCK_KEY})
        row = await session.get(NoticeTemplateModel, template_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Notice template not found.")
        await session.execute(
            update(NoticeTemplateModel).where(
                NoticeTemplateModel.module == row.module,
                NoticeTemplateModel.is_active.is_(True),
                NoticeTemplateModel.id != template_id,
            ).values(is_active=False)
        )
        row.is_active = True
        await session.flush()
        template = TemplateDetail.model_validate(row)
    await log_entity_action(
        es_client, user_id=actor_id, action="UPDATE", resource="notice_template", resource_id=template.id,
        after={"module": template.module, "is_active": True},
    )
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(status="success", data=template)
