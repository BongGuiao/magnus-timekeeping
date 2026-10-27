from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.payroll.application.loan_inputs import (
    EmployeeLoanInput,
    RestructureEmployeeLoanInput,
)
from app.payroll.application.loan_use_cases import EmployeeLoanUseCases
from app.payroll.domain.entities.loans import LoanSchedule
from app.payroll.infrastructure.loan_dependencies import get_employee_loan_use_cases


router = APIRouter(
    prefix="/payroll/loans",
    tags=["Payroll employee loans"],
    dependencies=[Depends(require_permission("payroll.manage"))],
)


class EmployeeLoanWriteSchema(BaseModel):
    employee_id: UUID
    payroll_group_id: UUID
    reference_number: str = Field(min_length=1, max_length=50)
    principal_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    installment_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    schedule: Literal["FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"]
    effective_from: date

    model_config = ConfigDict(extra="forbid")


class RestructureLoanWriteSchema(BaseModel):
    reference_number: str = Field(min_length=1, max_length=50)
    additional_principal: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    installment_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    schedule: Literal["FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"]
    effective_from: date

    model_config = ConfigDict(extra="forbid")


class EmployeeLoanRepaymentSchema(BaseModel):
    id: UUID
    loan_id: UUID
    cutoff_id: UUID
    gross_pay_run_id: UUID
    amount: Decimal
    created_at: datetime
    cutoff_code: str

    model_config = ConfigDict(from_attributes=True)


class EmployeeLoanSchema(BaseModel):
    id: UUID
    employee_id: UUID
    payroll_group_id: UUID
    reference_number: str
    principal_amount: Decimal
    installment_amount: Decimal
    schedule: LoanSchedule
    effective_from: date
    outstanding_balance: Decimal
    status: Literal["ACTIVE", "RETIRED", "PAID_OFF"]
    previous_loan_id: UUID | None
    created_at: datetime
    repayments: list[EmployeeLoanRepaymentSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


def _actor_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims.get("sub") or claims.get("user_id")))
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=401, detail="Authenticated user ID is missing.") from error


async def _audit(
    es_client: AsyncElasticsearch | None,
    *,
    actor_id: UUID,
    action: str,
    resource: str,
    resource_id: UUID,
    after: Any,
) -> None:
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        after=after,
    )


@router.get("", response_model=ResponseEnvelope[list[EmployeeLoanSchema]])
async def list_employee_loans(
    payroll_group_id: UUID,
    use_cases: EmployeeLoanUseCases = Depends(get_employee_loan_use_cases),
):
    return ResponseEnvelope(status="success", data=await use_cases.list_employee_loans(payroll_group_id))


@router.post(
    "",
    response_model=ResponseEnvelope[EmployeeLoanSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_loan(
    payload: EmployeeLoanWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: EmployeeLoanUseCases = Depends(get_employee_loan_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.create_employee_loan(
            EmployeeLoanInput(
                employee_id=payload.employee_id,
                payroll_group_id=payload.payroll_group_id,
                reference_number=payload.reference_number,
                principal_amount=payload.principal_amount,
                installment_amount=payload.installment_amount,
                schedule=payload.schedule,
                effective_from=payload.effective_from,
                actor_id=actor_id,
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await _audit(es_client, actor_id=actor_id, action="CREATE", resource="payroll_employee_loan", resource_id=result.id, after=result)
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/{loan_id}/retire",
    response_model=ResponseEnvelope[EmployeeLoanSchema],
)
async def retire_employee_loan(
    loan_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: EmployeeLoanUseCases = Depends(get_employee_loan_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.retire_employee_loan(loan_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await _audit(es_client, actor_id=actor_id, action="RETIRE", resource="payroll_employee_loan", resource_id=result.id, after=result)
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/{loan_id}/restructure",
    response_model=ResponseEnvelope[EmployeeLoanSchema],
    status_code=status.HTTP_201_CREATED,
)
async def restructure_employee_loan(
    loan_id: UUID,
    payload: RestructureLoanWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: EmployeeLoanUseCases = Depends(get_employee_loan_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_cases.restructure_employee_loan(
            loan_id,
            RestructureEmployeeLoanInput(
                reference_number=payload.reference_number,
                additional_principal=payload.additional_principal,
                installment_amount=payload.installment_amount,
                schedule=payload.schedule,
                effective_from=payload.effective_from,
                actor_id=actor_id,
            ),
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await _audit(es_client, actor_id=actor_id, action="RESTRUCTURE", resource="payroll_employee_loan", resource_id=result.id, after=result)
    return ResponseEnvelope(status="success", data=result)
