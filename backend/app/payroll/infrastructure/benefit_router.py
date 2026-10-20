from decimal import Decimal
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.payroll.application.benefit_inputs import (
    BenefitTypeInput,
    CutoffBenefitInput,
    EmployeeBenefitEntitlementInput,
    EmployeeBenefitDeductionInput,
)
from app.payroll.application.benefit_use_cases import BenefitUseCases
from app.payroll.application.use_cases import PayrollUseCases, SaveOpeningYtdBalanceInput
from app.payroll.infrastructure.dependencies import (
    get_benefit_use_cases,
    get_payroll_use_cases,
)


router = APIRouter(
    prefix="/payroll/benefits",
    tags=["Payroll benefits"],
    dependencies=[Depends(require_permission("payroll.manage"))],
)

BenefitCategoryValue = Literal[
    "CASH_ALLOWANCE",
    "ONE_TIME_BONUS",
    "REIMBURSEMENT",
    "EMPLOYER_PAID_INSURANCE",
    "NON_CASH",
    "EMPLOYEE_DEDUCTION",
]
TaxTreatmentValue = Literal["TAXABLE", "EXEMPT", "EXEMPT_LIMITED"]
DeductionScheduleValue = Literal["FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"]
BenefitPostingScheduleValue = Literal["FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"]


class BenefitTypeWriteSchema(BaseModel):
    payroll_group_id: UUID
    code: str = Field(min_length=1, max_length=30, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    category: BenefitCategoryValue
    tax_treatment: TaxTreatmentValue
    attendance_based: bool = False
    deduct_for_late: bool = False
    deduct_for_undertime: bool = False
    posting_schedule: BenefitPostingScheduleValue = "EVERY_CUTOFF"

    model_config = ConfigDict(extra="forbid")


class BenefitTypeSchema(BenefitTypeWriteSchema):
    id: UUID
    is_active: bool
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID
    row_version: int

    model_config = ConfigDict(from_attributes=True)


class CutoffBenefitWriteSchema(BaseModel):
    cutoff_id: UUID
    employee_id: UUID
    benefit_type_id: UUID
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class CutoffBenefitSchema(BaseModel):
    id: UUID
    cutoff_id: UUID
    employee_id: UUID
    benefit_type_id: UUID
    benefit_code: str
    benefit_name: str
    category: BenefitCategoryValue
    tax_treatment: TaxTreatmentValue
    amount: Decimal
    notes: str | None
    attendance_based: bool
    deduct_for_late: bool
    deduct_for_undertime: bool

    model_config = ConfigDict(from_attributes=True)


class EmployeeBenefitDeductionWriteSchema(BaseModel):
    employee_id: UUID
    benefit_type_id: UUID
    amount_per_occurrence: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    schedule: DeductionScheduleValue
    effective_from: date
    effective_to: date | None = None

    model_config = ConfigDict(extra="forbid")


class EmployeeBenefitDeductionSchema(EmployeeBenefitDeductionWriteSchema):
    id: UUID
    benefit_code: str
    benefit_name: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class EmployeeBenefitEntitlementWriteSchema(BaseModel):
    employee_id: UUID
    benefit_type_id: UUID
    amount_per_occurrence: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    effective_from: date
    effective_to: date | None = None

    model_config = ConfigDict(extra="forbid")


class EmployeeBenefitEntitlementSchema(EmployeeBenefitEntitlementWriteSchema):
    id: UUID
    benefit_code: str
    benefit_name: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class OpeningYtdBalanceWriteSchema(BaseModel):
    employee_id: UUID
    tax_year: int = Field(ge=1900, le=9999)
    taxable_income: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    tax_withheld: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    exempt_limited_benefits: Decimal = Field(ge=0, max_digits=14, decimal_places=2)

    model_config = ConfigDict(extra="forbid")


class OpeningYtdBalanceSchema(BaseModel):
    employee_id: UUID
    tax_year: int
    taxable_income: Decimal
    tax_withheld: Decimal
    exempt_limited_benefits: Decimal

    model_config = ConfigDict(from_attributes=True)


def _actor_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error


def _raise_benefit_error(error: ValueError) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


async def _audit(
    es_client: AsyncElasticsearch | None,
    *,
    actor_id: UUID,
    action: str,
    resource: str,
    resource_id: UUID,
    after: Any = None,
) -> None:
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        after=after,
    )


@router.get(
    "/ytd-balances",
    response_model=ResponseEnvelope[OpeningYtdBalanceSchema | None],
)
async def get_opening_ytd_balance(
    employee_id: UUID,
    tax_year: int = Query(ge=1900, le=9999),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
):
    try:
        balance = await use_cases.get_opening_ytd_balance(employee_id, tax_year)
    except ValueError as error:
        _raise_benefit_error(error)
    return ResponseEnvelope(status="success", data=balance)


@router.put(
    "/ytd-balances",
    response_model=ResponseEnvelope[OpeningYtdBalanceSchema],
)
async def put_opening_ytd_balance(
    payload: OpeningYtdBalanceWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        balance = await use_cases.save_opening_ytd_balance(
            SaveOpeningYtdBalanceInput(
                employee_id=payload.employee_id,
                tax_year=payload.tax_year,
                taxable_income=payload.taxable_income,
                tax_withheld=payload.tax_withheld,
                exempt_limited_benefits=payload.exempt_limited_benefits,
                actor_id=actor_id,
            )
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client,
        actor_id=actor_id,
        action="UPSERT",
        resource="payroll_opening_ytd_balance",
        resource_id=balance.id,
        after={
            "employee_id": str(balance.employee_id),
            "tax_year": balance.tax_year,
            "taxable_income": str(balance.taxable_income),
            "tax_withheld": str(balance.tax_withheld),
            "exempt_limited_benefits": str(balance.exempt_limited_benefits),
        },
    )
    return ResponseEnvelope(status="success", data=balance)


def _benefit_type_input(payload: BenefitTypeWriteSchema, actor_id: UUID) -> BenefitTypeInput:
    return BenefitTypeInput(
        payroll_group_id=payload.payroll_group_id,
        code=payload.code,
        name=payload.name,
        category=payload.category,
        tax_treatment=payload.tax_treatment,
        actor_id=actor_id,
        attendance_based=payload.attendance_based,
        deduct_for_late=payload.deduct_for_late,
        deduct_for_undertime=payload.deduct_for_undertime,
        posting_schedule=payload.posting_schedule,
    )


def _cutoff_benefit_input(payload: CutoffBenefitWriteSchema, actor_id: UUID) -> CutoffBenefitInput:
    return CutoffBenefitInput(
        cutoff_id=payload.cutoff_id,
        employee_id=payload.employee_id,
        benefit_type_id=payload.benefit_type_id,
        amount=payload.amount,
        notes=payload.notes,
        actor_id=actor_id,
    )


def _employee_deduction_input(
    payload: EmployeeBenefitDeductionWriteSchema,
    actor_id: UUID,
) -> EmployeeBenefitDeductionInput:
    return EmployeeBenefitDeductionInput(
        employee_id=payload.employee_id,
        benefit_type_id=payload.benefit_type_id,
        amount_per_occurrence=payload.amount_per_occurrence,
        schedule=payload.schedule,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        actor_id=actor_id,
    )


def _employee_benefit_entitlement_input(
    payload: EmployeeBenefitEntitlementWriteSchema,
    actor_id: UUID,
) -> EmployeeBenefitEntitlementInput:
    return EmployeeBenefitEntitlementInput(
        employee_id=payload.employee_id,
        benefit_type_id=payload.benefit_type_id,
        amount_per_occurrence=payload.amount_per_occurrence,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        actor_id=actor_id,
    )


@router.get("/types", response_model=ResponseEnvelope[list[BenefitTypeSchema]])
async def list_benefit_types(
    payroll_group_id: UUID,
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
):
    return ResponseEnvelope(
        status="success",
        data=await use_cases.list_benefit_types(payroll_group_id),
    )


@router.post(
    "/types",
    response_model=ResponseEnvelope[BenefitTypeSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_benefit_type(
    payload: BenefitTypeWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.create_benefit_type(_benefit_type_input(payload, actor_id))
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client, actor_id=actor_id, action="CREATE",
        resource="payroll_benefit_type", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put("/types/{benefit_type_id}", response_model=ResponseEnvelope[BenefitTypeSchema])
async def update_benefit_type(
    benefit_type_id: UUID,
    payload: BenefitTypeWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.update_benefit_type(
            benefit_type_id, _benefit_type_input(payload, actor_id)
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client, actor_id=actor_id, action="UPDATE",
        resource="payroll_benefit_type", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post("/types/{benefit_type_id}/deactivate", response_model=ResponseEnvelope[BenefitTypeSchema])
async def deactivate_benefit_type(
    benefit_type_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.set_benefit_type_active(benefit_type_id, False, actor_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    await _audit(
        es_client, actor_id=actor_id, action="DEACTIVATE",
        resource="payroll_benefit_type", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post("/types/{benefit_type_id}/activate", response_model=ResponseEnvelope[BenefitTypeSchema])
async def activate_benefit_type(
    benefit_type_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.set_benefit_type_active(benefit_type_id, True, actor_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    await _audit(
        es_client, actor_id=actor_id, action="ACTIVATE",
        resource="payroll_benefit_type", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/deductions",
    response_model=ResponseEnvelope[list[EmployeeBenefitDeductionSchema]],
)
async def list_employee_deductions(
    payroll_group_id: UUID,
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
):
    try:
        deductions = await use_cases.list_employee_deductions(payroll_group_id)
    except ValueError as error:
        _raise_benefit_error(error)
    return ResponseEnvelope(status="success", data=deductions)


@router.post(
    "/deductions",
    response_model=ResponseEnvelope[EmployeeBenefitDeductionSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_deduction(
    payload: EmployeeBenefitDeductionWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.save_employee_deduction(
            _employee_deduction_input(payload, actor_id)
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client, actor_id=actor_id, action="CREATE",
        resource="payroll_employee_benefit_deduction", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/deductions/{deduction_id}",
    response_model=ResponseEnvelope[EmployeeBenefitDeductionSchema],
)
async def update_employee_deduction(
    deduction_id: UUID,
    payload: EmployeeBenefitDeductionWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.save_employee_deduction(
            _employee_deduction_input(payload, actor_id), deduction_id
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client, actor_id=actor_id, action="UPDATE",
        resource="payroll_employee_benefit_deduction", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/deductions/{deduction_id}/{action}",
    response_model=ResponseEnvelope[EmployeeBenefitDeductionSchema],
)
async def set_employee_deduction_active(
    deduction_id: UUID,
    action: Literal["activate", "deactivate"],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.set_employee_deduction_active(
            deduction_id, action == "activate", actor_id
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    await _audit(
        es_client,
        actor_id=actor_id,
        action=action.upper(),
        resource="payroll_employee_benefit_deduction",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/entitlements",
    response_model=ResponseEnvelope[list[EmployeeBenefitEntitlementSchema]],
)
async def list_employee_benefit_entitlements(
    payroll_group_id: UUID,
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
):
    try:
        entitlements = await use_cases.list_employee_benefit_entitlements(payroll_group_id)
    except ValueError as error:
        _raise_benefit_error(error)
    return ResponseEnvelope(status="success", data=entitlements)


@router.post(
    "/entitlements",
    response_model=ResponseEnvelope[EmployeeBenefitEntitlementSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_benefit_entitlement(
    payload: EmployeeBenefitEntitlementWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.save_employee_benefit_entitlement(
            _employee_benefit_entitlement_input(payload, actor_id)
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client,
        actor_id=actor_id,
        action="CREATE",
        resource="payroll_employee_benefit_entitlement",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/entitlements/{entitlement_id}",
    response_model=ResponseEnvelope[EmployeeBenefitEntitlementSchema],
)
async def update_employee_benefit_entitlement(
    entitlement_id: UUID,
    payload: EmployeeBenefitEntitlementWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.save_employee_benefit_entitlement(
            _employee_benefit_entitlement_input(payload, actor_id),
            entitlement_id,
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client,
        actor_id=actor_id,
        action="UPDATE",
        resource="payroll_employee_benefit_entitlement",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/entitlements/{entitlement_id}/{action}",
    response_model=ResponseEnvelope[EmployeeBenefitEntitlementSchema],
)
async def set_employee_benefit_entitlement_active(
    entitlement_id: UUID,
    action: Literal["activate", "deactivate"],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.set_employee_benefit_entitlement_active(
            entitlement_id,
            action == "activate",
            actor_id,
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    await _audit(
        es_client,
        actor_id=actor_id,
        action=action.upper(),
        resource="payroll_employee_benefit_entitlement",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get("/cutoffs/{cutoff_id}", response_model=ResponseEnvelope[list[CutoffBenefitSchema]])
async def list_cutoff_benefits(
    cutoff_id: UUID,
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
):
    return ResponseEnvelope(status="success", data=await use_cases.list_cutoff_benefits(cutoff_id))


@router.post(
    "/cutoffs/{cutoff_id}",
    response_model=ResponseEnvelope[CutoffBenefitSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_cutoff_benefit(
    cutoff_id: UUID,
    payload: CutoffBenefitWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    if payload.cutoff_id != cutoff_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cutoff ID does not match the request path.")
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.save_cutoff_benefit(_cutoff_benefit_input(payload, actor_id))
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client, actor_id=actor_id, action="CREATE",
        resource="payroll_cutoff_benefit", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put("/entries/{entry_id}", response_model=ResponseEnvelope[CutoffBenefitSchema])
async def update_cutoff_benefit(
    entry_id: UUID,
    payload: CutoffBenefitWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.save_cutoff_benefit(
            _cutoff_benefit_input(payload, actor_id), entry_id
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client, actor_id=actor_id, action="UPDATE",
        resource="payroll_cutoff_benefit", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete("/entries/{entry_id}", response_model=ResponseEnvelope[dict[str, bool]])
async def delete_cutoff_benefit(
    entry_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: BenefitUseCases = Depends(get_benefit_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        await use_cases.delete_cutoff_benefit(entry_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_benefit_error(error)
    await _audit(
        es_client, actor_id=actor_id, action="DELETE",
        resource="payroll_cutoff_benefit", resource_id=entry_id,
    )
    return ResponseEnvelope(status="success", data={"deleted": True})
