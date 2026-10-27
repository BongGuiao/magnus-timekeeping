from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Date, bindparam, cast, exists, func, or_, select, text

from app.attendance.application.use_case import resolve_schedule_day
from app.attendance.infrastructure.db_model import OfficialBusinessRequestModel
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.db_model import UserModel
from app.auth.infrastructure.dependencies import require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    CutoffDeadlineError,
    require_attendance_open,
)

router = APIRouter(prefix="/attendance/official-business", tags=["Official Business"])

MANILA = ZoneInfo("Asia/Manila")
MAX_REQUEST_DURATION = timedelta(days=31)
BLOCKING_STATUSES = ("DRAFT", "PENDING", "APPROVED")


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class OfficialBusinessInputSchema(BaseModel):
    start_at: AwareDatetime
    end_at: AwareDatetime
    destination: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=5000)
    client_name: str | None = Field(default=None, max_length=200)
    geofence_id: UUID | None = None
    jo_reference: str | None = Field(default=None, max_length=100)
    vehicle_id: UUID | None = None
    requested_minutes: int | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_request(self) -> "OfficialBusinessInputSchema":
        self.destination = self.destination.strip()
        self.purpose = self.purpose.strip()
        if not self.destination:
            raise ValueError("destination cannot be blank.")
        if not self.purpose:
            raise ValueError("purpose cannot be blank.")
        self.client_name = _clean_optional(self.client_name)
        self.jo_reference = _clean_optional(self.jo_reference)
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at.")
        duration = self.end_at - self.start_at
        if duration > MAX_REQUEST_DURATION:
            raise ValueError("An official business request cannot exceed 31 days.")
        duration_minutes = int(duration.total_seconds() // 60)
        if duration_minutes <= 0:
            raise ValueError("The official business period must be at least one minute.")
        if self.requested_minutes is None:
            self.requested_minutes = duration_minutes
        elif self.requested_minutes > duration_minutes:
            raise ValueError(
                f"requested_minutes cannot exceed the {duration_minutes}-minute request period."
            )
        return self


class OfficialBusinessCreateSchema(OfficialBusinessInputSchema):
    submit: bool = False


class OfficialBusinessUpdateSchema(OfficialBusinessInputSchema):
    row_version: int = Field(ge=1)


class OfficialBusinessVersionSchema(BaseModel):
    row_version: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")


class OfficialBusinessDecisionSchema(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    approved_minutes: int | None = Field(default=None, gt=0)
    row_version: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_minutes(self) -> "OfficialBusinessDecisionSchema":
        if self.decision == "APPROVED" and self.approved_minutes is None:
            raise ValueError("approved_minutes is required when approving.")
        if self.decision == "REJECTED" and self.approved_minutes is not None:
            raise ValueError("approved_minutes must be empty when rejecting.")
        return self


class OfficialBusinessSchema(BaseModel):
    id: UUID
    request_no: str
    employee_id: UUID
    employee_code: str
    employee_name: str
    start_at: datetime
    end_at: datetime
    destination: str
    purpose: str
    client_name: str | None
    geofence_id: UUID | None
    geofence_name: str | None
    jo_reference: str | None
    vehicle_id: UUID | None
    vehicle_label: str | None
    requested_minutes: int
    approved_minutes: int | None
    status: str
    payroll_posted: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


class OfficialBusinessOptionSchema(BaseModel):
    id: UUID
    label: str


class OfficialBusinessOptionsSchema(BaseModel):
    geofences: list[OfficialBusinessOptionSchema]
    vehicles: list[OfficialBusinessOptionSchema]


def _user_id(claims: dict) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


def _reviewer(claims: dict) -> tuple[UUID, bool, UUID | None]:
    actor_id = _user_id(claims)
    is_admin = claims.get("role") == Role.ADMIN.value
    try:
        employee_id = (
            UUID(str(claims["employee_id"]))
            if claims.get("employee_id") is not None
            else None
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to a supervisor employee profile.",
        ) from error
    if not is_admin and employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to a supervisor employee profile.",
        )
    return actor_id, is_admin, employee_id


def _active_session(active_uow):
    if active_uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return active_uow.session


def _employee_name(employee: EmployeeModel) -> str:
    preferred_name = employee.preferred_name.strip() if employee.preferred_name else ""
    return preferred_name or " ".join(
        part
        for part in (employee.first_name, employee.middle_name, employee.last_name, employee.suffix)
        if part
    )


def _local_date(value: datetime) -> date:
    return value.astimezone(MANILA).date()


def _assignment_effective_on(on_date):
    return (
        EmploymentAssignmentModel.is_active.is_(True),
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= on_date,
        or_(
            EmploymentAssignmentModel.effective_to.is_(None),
            EmploymentAssignmentModel.effective_to >= on_date,
        ),
        or_(
            EmploymentAssignmentModel.separation_date.is_(None),
            EmploymentAssignmentModel.separation_date >= on_date,
        ),
    )


def _supervised_by(supervisor_employee_id: UUID):
    start_date = cast(func.timezone("Asia/Manila", OfficialBusinessRequestModel.start_at), Date)
    return exists().where(
        EmploymentAssignmentModel.employee_id == OfficialBusinessRequestModel.employee_id,
        EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
        *_assignment_effective_on(start_date),
    )


async def _employee_for_user(session, user_id: UUID, *, lock: bool = False) -> EmployeeModel:
    statement = (
        select(EmployeeModel)
        .join(UserModel, UserModel.employee_id == EmployeeModel.id)
        .where(
            UserModel.id == user_id,
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
        )
    )
    if lock:
        # Serializes overlap checks per employee without blocking FK key-share locks.
        statement = statement.with_for_update(of=EmployeeModel, key_share=True)
    employee = await session.scalar(statement)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an active employee profile.",
        )
    return employee


async def _vehicles_table_exists(session) -> bool:
    return bool(await session.scalar(text("SELECT to_regclass('fleet.vehicles') IS NOT NULL")))


async def _validate_within_schedule(
    session,
    employee_id: UUID,
    payload: OfficialBusinessInputSchema,
) -> None:
    """Official business may only be filed inside the employee's scheduled shift(s)."""
    windows: list[tuple[datetime, datetime]] = []
    # Start a day early so an overnight shift from the previous date is included.
    day = _local_date(payload.start_at) - timedelta(days=1)
    last_day = _local_date(payload.end_at)
    while day <= last_day:
        schedule = await resolve_schedule_day(session, employee_id, day)
        if (
            schedule.work_type == "REG"
            and schedule.expected_clock_in_at is not None
            and schedule.expected_clock_out_at is not None
            and schedule.expected_clock_out_at > schedule.expected_clock_in_at
        ):
            windows.append((schedule.expected_clock_in_at, schedule.expected_clock_out_at))
        day += timedelta(days=1)

    covered_until = payload.start_at
    for window_start, window_end in sorted(windows):
        if window_start > covered_until:
            break
        covered_until = max(covered_until, window_end)
        if covered_until >= payload.end_at:
            return

    relevant = [
        window
        for window in sorted(windows)
        if window[0] < payload.end_at + timedelta(hours=12)
        and window[1] > payload.start_at - timedelta(hours=12)
    ]
    if relevant:
        shifts = ", ".join(
            f"{start.astimezone(MANILA):%b %d %I:%M %p} - {end.astimezone(MANILA):%b %d %I:%M %p}"
            for start, end in relevant
        )
        detail = (
            "Official business must be within your scheduled shift. "
            f"Scheduled shift: {shifts}."
        )
    else:
        detail = "Official business must be within your scheduled shift. No working schedule covers this period."
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


async def _validate_request(
    session,
    employee_id: UUID,
    payload: OfficialBusinessInputSchema,
    exclude_request_id: UUID | None = None,
) -> None:
    start_date = _local_date(payload.start_at)
    company_ids = set(
        (
            await session.scalars(
                select(EmploymentAssignmentModel.company_id).where(
                    EmploymentAssignmentModel.employee_id == employee_id,
                    *_assignment_effective_on(start_date),
                )
            )
        ).all()
    )
    if not company_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No active employment assignment covers the official business start date.",
        )

    if payload.geofence_id is not None:
        geofence_id = await session.scalar(
            select(Geofence.id).where(
                Geofence.id == payload.geofence_id,
                Geofence.is_active.is_(True),
                Geofence.status == "ACTIVE",
                Geofence.company_id.in_(company_ids),
                Geofence.effective_from <= payload.start_at,
                or_(Geofence.effective_to.is_(None), Geofence.effective_to > payload.start_at),
            )
        )
        if geofence_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The selected geofence is not active for your company on the start date.",
            )

    if payload.vehicle_id is not None:
        vehicle_id = None
        if await _vehicles_table_exists(session):
            vehicle_id = await session.scalar(
                text(
                    "SELECT id FROM fleet.vehicles "
                    "WHERE id = :vehicle_id AND is_active AND company_id IN :company_ids"
                ).bindparams(bindparam("company_ids", expanding=True)),
                {"vehicle_id": payload.vehicle_id, "company_ids": list(company_ids)},
            )
        if vehicle_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The selected vehicle is not active for your company.",
            )

    await _validate_within_schedule(session, employee_id, payload)

    overlap = select(OfficialBusinessRequestModel.request_no).where(
        OfficialBusinessRequestModel.employee_id == employee_id,
        OfficialBusinessRequestModel.is_active.is_(True),
        OfficialBusinessRequestModel.status.in_(BLOCKING_STATUSES),
        OfficialBusinessRequestModel.start_at < payload.end_at,
        OfficialBusinessRequestModel.end_at > payload.start_at,
    )
    if exclude_request_id is not None:
        overlap = overlap.where(OfficialBusinessRequestModel.id != exclude_request_id)
    overlapping_no = await session.scalar(overlap.limit(1))
    if overlapping_no is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This period overlaps official business request {overlapping_no}.",
        )


def _apply_payload(request: OfficialBusinessRequestModel, payload: OfficialBusinessInputSchema) -> None:
    request.start_at = payload.start_at
    request.end_at = payload.end_at
    request.destination = payload.destination
    request.purpose = payload.purpose
    request.client_name = payload.client_name
    request.geofence_id = payload.geofence_id
    request.jo_reference = payload.jo_reference
    request.vehicle_id = payload.vehicle_id
    request.requested_minutes = payload.requested_minutes


async def _outputs(
    session,
    rows: list[tuple[OfficialBusinessRequestModel, EmployeeModel]],
) -> list[OfficialBusinessSchema]:
    geofence_ids = {request.geofence_id for request, _ in rows if request.geofence_id}
    vehicle_ids = {request.vehicle_id for request, _ in rows if request.vehicle_id}
    geofence_names: dict[UUID, str] = {}
    vehicle_labels: dict[UUID, str] = {}
    if geofence_ids:
        geofence_names = dict(
            (
                await session.execute(
                    select(Geofence.id, Geofence.geofence_name).where(Geofence.id.in_(geofence_ids))
                )
            ).all()
        )
    if vehicle_ids and await _vehicles_table_exists(session):
        vehicle_labels = {
            row.id: f"{row.vehicle_no} · {row.plate_no}"
            for row in (
                await session.execute(
                    text(
                        "SELECT id, vehicle_no, plate_no FROM fleet.vehicles WHERE id IN :vehicle_ids"
                    ).bindparams(bindparam("vehicle_ids", expanding=True)),
                    {"vehicle_ids": list(vehicle_ids)},
                )
            ).all()
        }
    return [
        OfficialBusinessSchema(
            id=request.id,
            request_no=request.request_no,
            employee_id=employee.id,
            employee_code=employee.employee_no,
            employee_name=_employee_name(employee),
            start_at=request.start_at,
            end_at=request.end_at,
            destination=request.destination,
            purpose=request.purpose,
            client_name=request.client_name,
            geofence_id=request.geofence_id,
            geofence_name=geofence_names.get(request.geofence_id) if request.geofence_id else None,
            jo_reference=request.jo_reference,
            vehicle_id=request.vehicle_id,
            vehicle_label=vehicle_labels.get(request.vehicle_id) if request.vehicle_id else None,
            requested_minutes=request.requested_minutes,
            approved_minutes=request.approved_minutes,
            status=request.status,
            payroll_posted=request.payroll_posted,
            row_version=request.row_version,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )
        for request, employee in rows
    ]


async def _refresh_output(session, request, employee) -> OfficialBusinessSchema:
    await session.flush()
    await session.refresh(request)
    return (await _outputs(session, [(request, employee)]))[0]


async def _own_request(
    session,
    request_id: UUID,
    employee_id: UUID,
    row_version: int,
    allowed_statuses: tuple[str, ...],
) -> OfficialBusinessRequestModel:
    request = await session.scalar(
        select(OfficialBusinessRequestModel)
        .with_for_update()
        .where(
            OfficialBusinessRequestModel.id == request_id,
            OfficialBusinessRequestModel.employee_id == employee_id,
            OfficialBusinessRequestModel.is_active.is_(True),
        )
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Official business request was not found for your account.",
        )
    if request.row_version != row_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This request was changed by another session. Reload and try again.",
        )
    if request.status not in allowed_statuses or request.payroll_posted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {request.status.lower()} official business request cannot be changed.",
        )
    return request


@router.get("/options", response_model=ResponseEnvelope[OfficialBusinessOptionsSchema])
async def get_official_business_options(
    claims: dict = Depends(require_permission("official_business.submit_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    user_id = _user_id(claims)
    today = datetime.now(MANILA).date()
    now = datetime.now(timezone.utc)
    async with uow as active_uow:
        session = _active_session(active_uow)
        employee = await _employee_for_user(session, user_id)
        company_ids = set(
            (
                await session.scalars(
                    select(EmploymentAssignmentModel.company_id).where(
                        EmploymentAssignmentModel.employee_id == employee.id,
                        EmploymentAssignmentModel.is_active.is_(True),
                        EmploymentAssignmentModel.status == "ACTIVE",
                        or_(
                            EmploymentAssignmentModel.effective_to.is_(None),
                            EmploymentAssignmentModel.effective_to >= today,
                        ),
                        or_(
                            EmploymentAssignmentModel.separation_date.is_(None),
                            EmploymentAssignmentModel.separation_date >= today,
                        ),
                    )
                )
            ).all()
        )
        geofences: list[OfficialBusinessOptionSchema] = []
        vehicles: list[OfficialBusinessOptionSchema] = []
        if company_ids:
            geofences = [
                OfficialBusinessOptionSchema(id=row.id, label=f"{row.geofence_name} ({row.geofence_code})")
                for row in (
                    await session.execute(
                        select(Geofence.id, Geofence.geofence_name, Geofence.geofence_code)
                        .where(
                            Geofence.company_id.in_(company_ids),
                            Geofence.is_active.is_(True),
                            Geofence.status == "ACTIVE",
                            or_(Geofence.effective_to.is_(None), Geofence.effective_to > now),
                        )
                        .order_by(Geofence.geofence_name)
                    )
                ).all()
            ]
            if await _vehicles_table_exists(session):
                vehicles = [
                    OfficialBusinessOptionSchema(id=row.id, label=f"{row.vehicle_no} · {row.plate_no}")
                    for row in (
                        await session.execute(
                            text(
                                "SELECT id, vehicle_no, plate_no FROM fleet.vehicles "
                                "WHERE is_active AND company_id IN :company_ids ORDER BY vehicle_no"
                            ).bindparams(bindparam("company_ids", expanding=True)),
                            {"company_ids": list(company_ids)},
                        )
                    ).all()
                ]
    return ResponseEnvelope(
        status="success",
        data=OfficialBusinessOptionsSchema(geofences=geofences, vehicles=vehicles),
    )


@router.get("", response_model=ResponseEnvelope[list[OfficialBusinessSchema]])
async def get_my_official_business_requests(
    claims: dict = Depends(require_permission("official_business.submit_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    user_id = _user_id(claims)
    async with uow as active_uow:
        session = _active_session(active_uow)
        employee = await _employee_for_user(session, user_id)
        requests = (
            await session.scalars(
                select(OfficialBusinessRequestModel)
                .where(
                    OfficialBusinessRequestModel.employee_id == employee.id,
                    OfficialBusinessRequestModel.is_active.is_(True),
                )
                .order_by(
                    OfficialBusinessRequestModel.start_at.desc(),
                    OfficialBusinessRequestModel.created_at.desc(),
                )
            )
        ).all()
        result = await _outputs(session, [(request, employee) for request in requests])
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "",
    response_model=ResponseEnvelope[OfficialBusinessSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_official_business_request(
    payload: OfficialBusinessCreateSchema,
    claims: dict = Depends(require_permission("official_business.submit_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _user_id(claims)
    async with uow as active_uow:
        session = _active_session(active_uow)
        employee = await _employee_for_user(session, user_id, lock=True)
        await _validate_request(session, employee.id, payload)
        if payload.submit:
            try:
                await require_attendance_open(
                    session,
                    employee.id,
                    _local_date(payload.start_at),
                    _local_date(payload.end_at),
                )
            except CutoffDeadlineError as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(error),
                ) from error
        request = OfficialBusinessRequestModel(
            request_no=f"OB-{_local_date(payload.start_at):%Y%m%d}-{uuid4().hex[:12].upper()}",
            employee_id=employee.id,
            status="PENDING" if payload.submit else "DRAFT",
            created_by=user_id,
            updated_by=user_id,
        )
        _apply_payload(request, payload)
        session.add(request)
        result = await _refresh_output(session, request, employee)

    await log_entity_action(
        es_client,
        user_id=user_id,
        action="SUBMIT" if payload.submit else "CREATE",
        resource="official_business_request",
        resource_id=str(result.id),
        after=result.model_dump(mode="json"),
    )
    return ResponseEnvelope(status="success", data=result)


@router.put("/{request_id}", response_model=ResponseEnvelope[OfficialBusinessSchema])
async def update_official_business_request(
    request_id: UUID,
    payload: OfficialBusinessUpdateSchema,
    claims: dict = Depends(require_permission("official_business.submit_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _user_id(claims)
    async with uow as active_uow:
        session = _active_session(active_uow)
        employee = await _employee_for_user(session, user_id, lock=True)
        request = await _own_request(session, request_id, employee.id, payload.row_version, ("DRAFT",))
        await _validate_request(session, employee.id, payload, exclude_request_id=request.id)
        _apply_payload(request, payload)
        request.updated_by = user_id
        request.row_version += 1
        result = await _refresh_output(session, request, employee)

    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="official_business_request",
        resource_id=str(request_id),
        after=result.model_dump(mode="json"),
    )
    return ResponseEnvelope(status="success", data=result)


@router.post("/{request_id}/submit", response_model=ResponseEnvelope[OfficialBusinessSchema])
async def submit_official_business_request(
    request_id: UUID,
    payload: OfficialBusinessVersionSchema,
    claims: dict = Depends(require_permission("official_business.submit_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _user_id(claims)
    async with uow as active_uow:
        session = _active_session(active_uow)
        employee = await _employee_for_user(session, user_id, lock=True)
        request = await _own_request(session, request_id, employee.id, payload.row_version, ("DRAFT",))
        try:
            await require_attendance_open(
                session,
                request.employee_id,
                _local_date(request.start_at),
                _local_date(request.end_at),
            )
        except CutoffDeadlineError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        # Re-validate because assignments, geofences, or vehicles may have changed since drafting.
        await _validate_request(
            session,
            employee.id,
            OfficialBusinessInputSchema(
                start_at=request.start_at,
                end_at=request.end_at,
                destination=request.destination,
                purpose=request.purpose,
                client_name=request.client_name,
                geofence_id=request.geofence_id,
                jo_reference=request.jo_reference,
                vehicle_id=request.vehicle_id,
                requested_minutes=request.requested_minutes,
            ),
            exclude_request_id=request.id,
        )
        request.status = "PENDING"
        request.updated_by = user_id
        request.row_version += 1
        result = await _refresh_output(session, request, employee)

    await log_entity_action(
        es_client,
        user_id=user_id,
        action="SUBMIT",
        resource="official_business_request",
        resource_id=str(request_id),
        after={"status": result.status},
    )
    return ResponseEnvelope(status="success", data=result)


@router.post("/{request_id}/cancel", response_model=ResponseEnvelope[OfficialBusinessSchema])
async def cancel_official_business_request(
    request_id: UUID,
    payload: OfficialBusinessVersionSchema,
    claims: dict = Depends(require_permission("official_business.submit_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _user_id(claims)
    async with uow as active_uow:
        session = _active_session(active_uow)
        employee = await _employee_for_user(session, user_id)
        request = await _own_request(
            session, request_id, employee.id, payload.row_version, ("DRAFT", "PENDING"),
        )
        previous_status = request.status
        request.status = "CANCELLED"
        request.updated_by = user_id
        request.row_version += 1
        result = await _refresh_output(session, request, employee)

    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CANCEL",
        resource="official_business_request",
        resource_id=str(request_id),
        before={"status": previous_status},
        after={"status": result.status},
    )
    return ResponseEnvelope(status="success", data=result)


@router.get("/pending", response_model=ResponseEnvelope[list[OfficialBusinessSchema]])
async def get_pending_official_business_requests(
    claims: dict = Depends(require_permission("official_business.approve_team")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _, is_admin, reviewer_employee_id = _reviewer(claims)
    async with uow as active_uow:
        session = _active_session(active_uow)
        statement = (
            select(OfficialBusinessRequestModel, EmployeeModel)
            .join(EmployeeModel, EmployeeModel.id == OfficialBusinessRequestModel.employee_id)
            .where(
                OfficialBusinessRequestModel.status == "PENDING",
                OfficialBusinessRequestModel.is_active.is_(True),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
            )
            .order_by(OfficialBusinessRequestModel.created_at, EmployeeModel.employee_no)
        )
        if not is_admin:
            statement = statement.where(_supervised_by(reviewer_employee_id))
        if reviewer_employee_id is not None:
            statement = statement.where(OfficialBusinessRequestModel.employee_id != reviewer_employee_id)
        rows = [tuple(row) for row in (await session.execute(statement)).all()]
        result = await _outputs(session, rows)
    return ResponseEnvelope(status="success", data=result)


@router.post("/{request_id}/decision", response_model=ResponseEnvelope[OfficialBusinessSchema])
async def decide_official_business_request(
    request_id: UUID,
    payload: OfficialBusinessDecisionSchema,
    claims: dict = Depends(require_permission("official_business.approve_team")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id, is_admin, reviewer_employee_id = _reviewer(claims)
    async with uow as active_uow:
        session = _active_session(active_uow)
        statement = (
            select(OfficialBusinessRequestModel, EmployeeModel)
            .with_for_update(of=OfficialBusinessRequestModel)
            .join(EmployeeModel, EmployeeModel.id == OfficialBusinessRequestModel.employee_id)
            .where(
                OfficialBusinessRequestModel.id == request_id,
                OfficialBusinessRequestModel.status == "PENDING",
                OfficialBusinessRequestModel.is_active.is_(True),
            )
        )
        if not is_admin:
            statement = statement.where(_supervised_by(reviewer_employee_id))
        row = (await session.execute(statement)).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending official business request was not found for your assigned employees.",
            )
        request, employee = row
        if reviewer_employee_id == employee.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot decide your own official business request.",
            )
        if request.row_version != payload.row_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This request was changed by another session. Reload and try again.",
            )
        try:
            await require_attendance_open(
                session,
                request.employee_id,
                _local_date(request.start_at),
                _local_date(request.end_at),
            )
        except CutoffDeadlineError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        if payload.approved_minutes is not None and payload.approved_minutes > request.requested_minutes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Approved minutes cannot exceed the requested minutes.",
            )
        request.status = payload.decision
        request.approved_minutes = payload.approved_minutes
        request.updated_by = actor_id
        request.row_version += 1
        result = await _refresh_output(session, request, employee)

    await log_entity_action(
        es_client,
        user_id=actor_id,
        action=payload.decision,
        resource="official_business_request",
        resource_id=str(request_id),
        after={"status": result.status, "approved_minutes": result.approved_minutes},
    )
    return ResponseEnvelope(status="success", data=result)
