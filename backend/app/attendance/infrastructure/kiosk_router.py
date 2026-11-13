from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from anyio import to_thread
from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.accounts import employee_display_name
from app.auth.infrastructure.dependencies import require_system_admin
from app.attendance.application.use_case import (
    ClockAttendanceInputDTO, ClockAttendanceUseCase, GetLastAttendanceInputDTO,
    GetLastAttendanceUseCase, RecordBreakInputDTO, RecordBreakUseCase,
)
from app.attendance.infrastructure.clock_policy import get_client_ip
from app.attendance.infrastructure.clock_router import ClockResponseSchema, BreakResponseSchema, _read_face_image
from app.attendance.infrastructure.dependencies import get_clock_attendance_use_case, get_last_attendance_use_case, get_record_break_use_case
from app.attendance.infrastructure.kiosk_models import KioskDeviceModel
from app.attendance.infrastructure.kiosk_service import KioskService, clock_payload, current_user_company, require_active_location
from app.attendance.infrastructure.overtime_adapters import CeleryRecentAttendanceRefresher
from app.core.generics.mapper import GenericMapper, ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.location.infrastructure.db_model import Location

router = APIRouter(prefix="/kiosk", tags=["Attendance kiosks"])


class Enrollment(BaseModel):
    device_id: UUID
    device_name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    public_key_jwk: dict = Field(max_length=8)


class Challenge(BaseModel):
    device_id: UUID
    purpose: Literal["STATUS", "IDENTIFY", "CLOCK", "BREAK"]
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Proof(BaseModel):
    challenge_id: UUID
    signature: str = Field(min_length=86, max_length=86)


class Identify(Proof):
    employee_code: str = Field(min_length=1, max_length=30)


class Approval(BaseModel):
    pairing_code: str = Field(pattern=r"^[A-Fa-f0-9]{16}$")
    location_id: UUID


def get_kiosk_service(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> KioskService:
    return KioskService(uow)


def device_summary(device: KioskDeviceModel) -> dict:
    return {
        "id": device.id, "device_name": device.device_name, "status": device.status,
        "company_id": device.company_id, "location_id": device.location_id,
        "approved_at": device.approved_at, "revoked_at": device.revoked_at, "last_seen_at": device.last_seen_at,
    }


@router.post("/enroll")
async def enroll(payload: Enrollment, service: KioskService = Depends(get_kiosk_service)):
    return ResponseEnvelope(data=await service.enroll(payload.device_id, payload.device_name.strip(), payload.public_key_jwk))


@router.post("/challenge")
async def challenge(payload: Challenge, service: KioskService = Depends(get_kiosk_service)):
    return ResponseEnvelope(data=await service.challenge(payload.device_id, payload.purpose, payload.payload_hash))


@router.post("/status")
async def status(payload: Proof, service: KioskService = Depends(get_kiosk_service)):
    device = await service.authorize(payload.challenge_id, payload.signature, "STATUS", "")
    return ResponseEnvelope(data=device_summary(device))


@router.post("/identify")
async def identify(
    payload: Identify, service: KioskService = Depends(get_kiosk_service),
    last: GetLastAttendanceUseCase = Depends(get_last_attendance_use_case),
):
    code = payload.employee_code.strip()
    device = await service.authorize(payload.challenge_id, payload.signature, "IDENTIFY", code)
    user, employee = await service.employee(device, code=code)
    attendance = await last.execute(GetLastAttendanceInputDTO(user_id=user.id, for_kiosk=True))
    return ResponseEnvelope(data={
        "user": {
            "id": user.id, "employee_id": employee.id, "employee_code": employee.employee_no,
            "employee_name": employee_display_name(GenericMapper.to_entity(employee, EmployeeEntity)), "is_active": True,
            "email": "", "role": "",
        },
        "last_attendance": attendance,
    })


@router.post("/clock", response_model=ResponseEnvelope[ClockResponseSchema], status_code=201)
async def clock(
    request: Request,
    file: UploadFile = File(...),
    user_id: UUID = Form(...),
    action: Literal["clock_in", "clock_out"] = Form(...),
    challenge_id: UUID = Form(...),
    signature: str = Form(..., min_length=86, max_length=86),
    service: KioskService = Depends(get_kiosk_service),
    use_case: ClockAttendanceUseCase = Depends(get_clock_attendance_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    image = await _read_face_image(file)
    device = await service.authorize(challenge_id, signature, "CLOCK", clock_payload(user_id, action, image))
    await service.employee(device, user_id=user_id)
    result = await use_case.execute(ClockAttendanceInputDTO(
        user_id=user_id, image_bytes=image, requested_action=action,
        kiosk_action=True, actor_id=user_id,
        clock_out_confirmed=action == "clock_out", device_approved=True, enforce_geofence=False,
        clock_channel={
            "channel": "kiosk", "kiosk_device_id": str(device.id), "client_ip": get_client_ip(request),
            "company_id": str(device.company_id), "location_id": str(device.location_id),
        },
        punch_metadata={
            "kiosk_device_id": str(device.id), "kiosk_device_name": device.device_name,
            "performed_by": str(user_id),
        },
    ))
    await to_thread.run_sync(CeleryRecentAttendanceRefresher().request_refresh, user_id)
    await log_entity_action(
        es_client, user_id=user_id, action="CREATE" if result.action == "clock_in" else "UPDATE",
        resource="attendance", resource_id=result.employee_code,
        after={**asdict(result), "kiosk_device_id": str(device.id), "kiosk_device_name": device.device_name},
    )
    return ResponseEnvelope(data=ClockResponseSchema(
        **{name: getattr(result, name) for name in ClockResponseSchema.model_fields}
    ))


@router.post("/break", response_model=ResponseEnvelope[BreakResponseSchema], status_code=201)
async def record_break(
    request: Request,
    file: UploadFile = File(...),
    user_id: UUID = Form(...),
    action: Literal[
        "first_break_out_at", "first_break_in_at", "meal_break_out_at", "meal_break_in_at",
        "second_break_out_at", "second_break_in_at", "ot_break_out_at", "ot_break_in_at",
    ] = Form(...),
    challenge_id: UUID = Form(...),
    signature: str = Form(..., min_length=86, max_length=86),
    service: KioskService = Depends(get_kiosk_service),
    use_case: RecordBreakUseCase = Depends(get_record_break_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    image = await _read_face_image(file)
    device = await service.authorize(challenge_id, signature, "BREAK", clock_payload(user_id, action, image))
    await service.employee(device, user_id=user_id)
    result = await use_case.execute(RecordBreakInputDTO(
        user_id=user_id, image_bytes=image, break_type=action, actor_id=user_id,
        device_proof={"device_id": str(device.id), "platform": "KIOSK"},
        punch_metadata={
            "channel": "kiosk", "kiosk_device_id": str(device.id), "client_ip": get_client_ip(request),
            "kiosk_device_name": device.device_name, "performed_by": str(user_id),
        },
    ))
    await to_thread.run_sync(CeleryRecentAttendanceRefresher().request_refresh, user_id)
    await log_entity_action(
        es_client, user_id=user_id, action="UPDATE", resource="attendance_break",
        resource_id=result.employee_code,
        after={**asdict(result), "kiosk_device_id": str(device.id), "kiosk_device_name": device.device_name},
    )
    return ResponseEnvelope(data=BreakResponseSchema(
        **{name: getattr(result, name) for name in BreakResponseSchema.model_fields}
    ))


@router.get("/devices")
async def list_devices(
    claims: dict = Depends(require_system_admin), uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        company = await current_user_company(uow.session, UUID(claims["sub"]))
        devices = (await uow.session.execute(
            select(KioskDeviceModel, Location.location_name)
            .outerjoin(Location, Location.id == KioskDeviceModel.location_id)
            .where(KioskDeviceModel.status != "PENDING", KioskDeviceModel.company_id == company.id)
            .order_by(KioskDeviceModel.created_at.desc())
        )).all()
        return ResponseEnvelope(data=[
            {**device_summary(device), "location_name": location_name}
            for device, location_name in devices
        ])


@router.get("/company")
async def get_company(
    claims: dict = Depends(require_system_admin), uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        company = await current_user_company(uow.session, UUID(claims["sub"]))
        return ResponseEnvelope(data={"id": company.id, "legal_name": company.legal_name})


@router.post("/approve")
async def approve(
    payload: Approval, claims: dict = Depends(require_system_admin),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    now = datetime.now(timezone.utc)
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        company = await current_user_company(uow.session, UUID(claims["sub"]))
        device = await uow.session.scalar(
            select(KioskDeviceModel).where(KioskDeviceModel.pairing_code == payload.pairing_code.upper()).with_for_update()
        )
        if device is None or device.status != "PENDING" or device.pairing_expires_at <= now:
            raise HTTPException(409, "Pairing code is invalid, expired, or already used.")
        await require_active_location(uow.session, company.id, payload.location_id)
        device.company_id, device.location_id = company.id, payload.location_id
        device.status, device.approved_at, device.approved_by = "APPROVED", now, UUID(claims["sub"])
        summary = device_summary(device)
    await log_entity_action(es_client, user_id=claims["sub"], action="UPDATE", resource="kiosk_device", resource_id=device.id, after=summary)
    return ResponseEnvelope(data=summary)


@router.post("/devices/{device_id}/revoke")
async def revoke(
    device_id: UUID, claims: dict = Depends(require_system_admin),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        company = await current_user_company(uow.session, UUID(claims["sub"]))
        device = await uow.session.get(KioskDeviceModel, device_id, with_for_update=True)
        if device is None or device.company_id != company.id:
            raise HTTPException(404, "Kiosk not found.")
        device.status, device.revoked_at, device.revoked_by = "REVOKED", datetime.now(timezone.utc), UUID(claims["sub"])
        summary = device_summary(device)
    await log_entity_action(es_client, user_id=claims["sub"], action="UPDATE", resource="kiosk_device", resource_id=device.id, after=summary)
    return ResponseEnvelope(data=summary)
