from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.leaves.application.leave_records_use_case import (
    BALANCE_FIELDS,
    _entitlement_assignment_query,
    _to_entity,
    _validate_entitlement_grant_rules,
    calculate_available_minutes,
)
from app.filemaintenance.leaves.domain.entities.leave_records import EmployeeEntitlementEntity
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.entitlement_upload_csv import (
    AMOUNT_COLUMNS,
    EntitlementUploadFile,
    RawEntitlementUploadRow,
    read_entitlement_upload_csv,
)
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import EmployeeEntitlementModel

_NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$")
_YEAR = re.compile(r"^[0-9]{4}$")
_MINUTES_PER_UNIT = {"MINUTES": 1, "HOURS": 60, "DAYS": 480}
_MIN_INT = -(2**31)
_MAX_INT = 2**31 - 1
_NEGATIVE_COLUMNS = {"opening_balance", "adjustment"}


@dataclass
class EntitlementUploadPreviewRow:
    row_no: int
    employee_no: str
    leave_code: str
    entitlement_year: int | None
    employee_name: str | None
    leave_name: str | None
    unit_type: str | None
    action: Literal["CREATE", "UPDATE"] | None
    errors: list[str]
    before: dict[str, int] | None
    after: dict[str, int] | None


@dataclass
class EntitlementUploadPreview:
    is_valid: bool
    error_count: int
    file_errors: list[str]
    rows: list[EntitlementUploadPreviewRow]
    preview_token: str | None


@dataclass
class EntitlementUploadChange:
    action: Literal["CREATE", "UPDATE"]
    before: EmployeeEntitlementEntity | None
    after: EmployeeEntitlementEntity


@dataclass
class EntitlementUploadResult:
    changes: list[EntitlementUploadChange]


class EntitlementUploadInvalidError(ValueError):
    pass


class EntitlementUploadChangedError(ValueError):
    pass


@dataclass
class _ParsedRow:
    row_no: int
    employee_no: str
    leave_code: str
    year: int | None
    amounts: dict[str, Decimal]
    errors: list[str]


@dataclass
class _ResolvedRow:
    preview: EntitlementUploadPreviewRow
    employee_id: UUID
    company_id: UUID
    leave_type_id: UUID
    year: int
    amounts: dict[str, int]
    existing: EmployeeEntitlementModel | None = None


def _parse_row(raw: RawEntitlementUploadRow) -> _ParsedRow:
    errors: list[str] = []
    employee_no = raw.values.get("employee_no", "").strip()
    leave_code = raw.values.get("leave_code", "").strip()
    for column, value in (("employee_no", employee_no), ("leave_code", leave_code)):
        if not value:
            errors.append(f"{column} is required.")
        elif len(value) > 30 or any(ord(char) < 32 or ord(char) == 127 for char in value):
            errors.append(f"{column} must be at most 30 characters and contain no control characters.")

    year_text = raw.values.get("entitlement_year", "").strip()
    year = int(year_text) if _YEAR.fullmatch(year_text) else None
    if year is None or not 1900 <= year <= 2200:
        errors.append("entitlement_year must be an integer from 1900 to 2200.")
        year = None

    amounts: dict[str, Decimal] = {}
    for column in AMOUNT_COLUMNS:
        value = raw.values.get(column, "").strip()
        if not value or len(value) > 32 or not _NUMBER.fullmatch(value):
            errors.append(f"{column} must be a number; enter 0 when there is no balance.")
            continue
        try:
            amount = Decimal(value)
        except InvalidOperation:
            errors.append(f"{column} must be a valid number.")
            continue
        if amount < 0 and column not in _NEGATIVE_COLUMNS:
            errors.append(f"{column} cannot be negative.")
        elif abs(amount) > _MAX_INT + 1:
            errors.append(f"{column} is too large.")
        else:
            amounts[column] = amount
    return _ParsedRow(raw.row_no, employee_no, leave_code, year, amounts, errors)


def _to_minutes(amounts: dict[str, Decimal], unit: str) -> tuple[dict[str, int], list[str]]:
    result: dict[str, int] = {}
    errors: list[str] = []
    factor = _MINUTES_PER_UNIT[unit]
    for column, field in AMOUNT_COLUMNS.items():
        amount = amounts[column]
        if unit == "MINUTES" and amount != amount.to_integral_value():
            errors.append(f"{column} must be a whole number for a minutes-based leave type.")
            continue
        # Match the existing form's Math.round, including negative half-minute values.
        with localcontext() as context:
            context.prec = 40
            minutes = int((amount * factor + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
        if not _MIN_INT <= minutes <= _MAX_INT:
            errors.append(f"{column} is too large when converted to minutes.")
        else:
            result[field] = minutes
    if not errors:
        available = calculate_available_minutes(result)
        if not _MIN_INT <= available <= _MAX_INT:
            errors.append("The calculated available balance is too large.")
        else:
            result["available_minutes"] = available
    return result, errors


def _balance_values(model: EmployeeEntitlementModel) -> dict[str, int]:
    values = {field: getattr(model, field) for field in BALANCE_FIELDS}
    values["available_minutes"] = calculate_available_minutes(values)
    return values


def _preview(
    rows: list[EntitlementUploadPreviewRow],
    file_errors: list[str],
    token: str | None = None,
) -> EntitlementUploadPreview:
    error_count = len(file_errors) + sum(len(row.errors) for row in rows)
    return EntitlementUploadPreview(
        is_valid=error_count == 0 and bool(rows),
        error_count=error_count,
        file_errors=file_errors,
        rows=rows,
        preview_token=token,
    )


def _fingerprint(content: bytes, resolved: list[_ResolvedRow]) -> str:
    rows = []
    for row in resolved:
        existing = row.existing
        rows.append({
            "employee_id": str(row.employee_id),
            "leave_type_id": str(row.leave_type_id),
            "year": row.year,
            "unit_type": row.preview.unit_type,
            "after": row.amounts,
            "existing_id": str(existing.id) if existing else None,
            "existing_balance": _balance_values(existing) if existing else None,
            "stored_available": existing.available_minutes if existing else None,
            "last_calculated_at": (
                existing.last_calculated_at.isoformat()
                if existing and existing.last_calculated_at else None
            ),
        })
    payload = {
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "rows": rows,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _evaluate(
    session: AsyncSession,
    content: bytes,
    upload: EntitlementUploadFile,
    today: date,
    *,
    lock: bool,
) -> tuple[EntitlementUploadPreview, list[_ResolvedRow]]:
    if upload.file_errors:
        return _preview([], list(upload.file_errors)), []

    parsed = [_parse_row(row) for row in upload.rows]
    by_key: dict[tuple[str, str, int], list[_ParsedRow]] = defaultdict(list)
    for row in parsed:
        if row.employee_no and row.leave_code and row.year is not None:
            by_key[(row.employee_no.upper(), row.leave_code.upper(), row.year)].append(row)
    for duplicates in by_key.values():
        if len(duplicates) > 1:
            numbers = ", ".join(str(row.row_no) for row in duplicates[:10])
            if len(duplicates) > 10:
                numbers += f", and {len(duplicates) - 10} more"
            for row in duplicates:
                row.errors.append(f"Duplicate employee, leave code, and year in rows {numbers}.")

    previews = [
        EntitlementUploadPreviewRow(
            row_no=row.row_no,
            employee_no=row.employee_no,
            leave_code=row.leave_code,
            entitlement_year=row.year,
            employee_name=None,
            leave_name=None,
            unit_type=None,
            action=None,
            errors=list(row.errors),
            before=None,
            after=None,
        )
        for row in parsed
    ]
    valid_rows = [row for row in parsed if not row.errors]
    if not valid_rows:
        return _preview(previews, []), []

    employee_codes = {row.employee_no.upper() for row in valid_rows}
    employee_result = await session.execute(
        select(EmployeeModel).where(func.upper(EmployeeModel.employee_no).in_(employee_codes))
    )
    employees_by_code: dict[str, list[EmployeeModel]] = defaultdict(list)
    for employee in employee_result.scalars().all():
        employees_by_code[employee.employee_no.upper()].append(employee)

    employee_ids = {employee.id for group in employees_by_code.values() for employee in group}
    assignments: dict[UUID, EmploymentAssignmentModel] = {}
    if employee_ids:
        assignment_result = await session.execute(
            _entitlement_assignment_query(employee_ids, today)
        )
        for assignment in assignment_result.scalars().all():
            assignments.setdefault(assignment.employee_id, assignment)

    company_ids = {assignment.company_id for assignment in assignments.values()}
    leave_codes = {row.leave_code.upper() for row in valid_rows}
    types_by_key: dict[tuple[UUID, str], list[LeaveTypeModel]] = defaultdict(list)
    if company_ids:
        type_result = await session.execute(
            select(LeaveTypeModel).where(
                LeaveTypeModel.company_id.in_(company_ids),
                func.upper(LeaveTypeModel.leave_code).in_(leave_codes),
                LeaveTypeModel.is_active.is_(True),
                LeaveTypeModel.status == "ACTIVE",
                LeaveTypeModel.effective_from <= today,
                LeaveTypeModel.effective_to.is_(None) | (LeaveTypeModel.effective_to >= today),
            )
        )
        for leave_type in type_result.scalars().all():
            types_by_key[(leave_type.company_id, leave_type.leave_code.upper())].append(leave_type)

    resolved: list[_ResolvedRow] = []
    for row, item in zip(parsed, previews):
        if item.errors or row.year is None:
            continue
        matches = employees_by_code.get(row.employee_no.upper(), [])
        if len(matches) != 1:
            item.errors.append(
                "Employee number was not found." if not matches
                else "Employee number is ambiguous; use a unique employee number."
            )
            continue
        employee = matches[0]
        item.employee_name = employee.preferred_name or f"{employee.first_name} {employee.last_name}".strip()
        assignment = assignments.get(employee.id)
        if assignment is None:
            item.errors.append("The employee has no active employment assignment.")
            continue
        types = types_by_key.get((assignment.company_id, row.leave_code.upper()), [])
        if len(types) != 1:
            item.errors.append(
                "No currently active leave type with this code exists in the employee's company."
                if not types else "Multiple active leave types use this code in the employee's company."
            )
            continue
        leave_type = types[0]
        item.leave_name = leave_type.leave_name
        item.unit_type = leave_type.unit_type
        try:
            _validate_entitlement_grant_rules(assignment, leave_type, today)
        except ValueError as error:
            item.errors.append(str(error))
            continue
        if leave_type.unit_type not in _MINUTES_PER_UNIT:
            item.errors.append("The leave type has an unsupported unit.")
            continue
        amounts, amount_errors = _to_minutes(row.amounts, leave_type.unit_type)
        if amount_errors:
            item.errors.extend(amount_errors)
            continue
        resolved.append(_ResolvedRow(item, employee.id, assignment.company_id, leave_type.id, row.year, amounts))

    if resolved:
        keys = {
            (row.employee_id, row.company_id, row.preview.leave_code.upper(), row.year)
            for row in resolved
        }
        statement = (
            select(EmployeeEntitlementModel, LeaveTypeModel)
            .join(LeaveTypeModel, LeaveTypeModel.id == EmployeeEntitlementModel.leave_type_id)
            .where(tuple_(
                EmployeeEntitlementModel.employee_id,
                LeaveTypeModel.company_id,
                func.upper(LeaveTypeModel.leave_code),
                EmployeeEntitlementModel.entitlement_year,
            ).in_(keys))
            .order_by(
                EmployeeEntitlementModel.employee_id,
                EmployeeEntitlementModel.leave_type_id,
                EmployeeEntitlementModel.entitlement_year,
            )
        )
        if lock:
            statement = statement.with_for_update(of=EmployeeEntitlementModel)
        entitlement_result = await session.execute(statement)
        existing: dict[tuple[UUID, UUID, str, int], list[EmployeeEntitlementModel]] = defaultdict(list)
        for entitlement, leave_type in entitlement_result.all():
            existing[(
                entitlement.employee_id, leave_type.company_id,
                leave_type.leave_code.upper(), entitlement.entitlement_year,
            )].append(entitlement)
        for row in resolved:
            matches = existing.get((
                row.employee_id, row.company_id, row.preview.leave_code.upper(), row.year,
            ), [])
            if any(item.leave_type_id != row.leave_type_id for item in matches) or len(matches) > 1:
                row.preview.errors.append(
                    "An entitlement already exists for another version of this leave code and year. "
                    "Resolve it before uploading."
                )
                continue
            row.existing = matches[0] if matches else None
            row.preview.action = "UPDATE" if row.existing else "CREATE"
            row.preview.before = _balance_values(row.existing) if row.existing else None
            row.preview.after = dict(row.amounts)

    preview = _preview(previews, [])
    if preview.is_valid:
        preview.preview_token = _fingerprint(content, resolved)
    return preview, resolved


def _constraint_name(error: IntegrityError) -> str | None:
    original = error.orig
    cause = getattr(original, "__cause__", None)
    return (
        getattr(original, "constraint_name", None)
        or getattr(getattr(original, "diag", None), "constraint_name", None)
        or getattr(cause, "constraint_name", None)
    )


class EntitlementUploadUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def preview(self, content: bytes) -> EntitlementUploadPreview:
        upload = read_entitlement_upload_csv(content)
        if upload.file_errors:
            return _preview([], list(upload.file_errors))
        async with self.uow as active_uow:
            if active_uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            preview, _ = await _evaluate(
                active_uow.session, content, upload,
                datetime.now(ZoneInfo("Asia/Manila")).date(), lock=False,
            )
            return preview

    async def apply(self, content: bytes, preview_token: str) -> EntitlementUploadResult:
        upload = read_entitlement_upload_csv(content)
        if upload.file_errors:
            raise EntitlementUploadInvalidError("The file is invalid. Check it again before uploading.")
        if not re.fullmatch(r"[0-9a-f]{64}", preview_token):
            raise EntitlementUploadInvalidError("Check the file before uploading it.")
        try:
            async with self.uow as active_uow:
                session = active_uow.session
                if session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                preview, resolved = await _evaluate(
                    session, content, upload,
                    datetime.now(ZoneInfo("Asia/Manila")).date(), lock=True,
                )
                if not preview.is_valid or preview.preview_token is None:
                    raise EntitlementUploadInvalidError(
                        "The file is no longer valid. Check it again before uploading."
                    )
                if not hmac.compare_digest(preview.preview_token, preview_token):
                    raise EntitlementUploadChangedError(
                        "The file or existing entitlement balances changed. Check the file again before uploading."
                    )

                now = datetime.now(timezone.utc)
                pending: list[tuple[Literal["CREATE", "UPDATE"], EmployeeEntitlementEntity | None, EmployeeEntitlementModel]] = []
                for row in resolved:
                    model = row.existing
                    if model is None:
                        model = EmployeeEntitlementModel(
                            employee_id=row.employee_id,
                            leave_type_id=row.leave_type_id,
                            entitlement_year=row.year,
                        )
                        session.add(model)
                        action: Literal["CREATE", "UPDATE"] = "CREATE"
                        before = None
                    else:
                        action = "UPDATE"
                        before = _to_entity(model, EmployeeEntitlementEntity)
                    for field, value in row.amounts.items():
                        setattr(model, field, value)
                    model.last_calculated_at = now
                    pending.append((action, before, model))
                await session.flush()
                if any(model.id is None for _, _, model in pending):
                    raise RuntimeError("An uploaded entitlement did not receive an ID.")
                changes = [
                    EntitlementUploadChange(action, before, _to_entity(model, EmployeeEntitlementEntity))
                    for action, before, model in pending
                ]
                return EntitlementUploadResult(changes)
        except IntegrityError as error:
            if _constraint_name(error) == "uq_employee_entitlements_employee_type_year":
                raise EntitlementUploadChangedError(
                    "An entitlement was created during the upload. Check the file again before uploading."
                ) from error
            raise
