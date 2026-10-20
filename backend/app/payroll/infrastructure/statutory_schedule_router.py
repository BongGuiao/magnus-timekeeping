from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Awaitable, Literal, TypeVar
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import (
    get_current_user_claims,
    require_permission,
)
from app.core.generics.mapper import ResponseEnvelope
from app.payroll.application.statutory_schedule_inputs import (
    ContributionBracketInput,
    ContributionScheduleInput,
    WithholdingTaxBracketInput,
    WithholdingTaxScheduleInput,
)
from app.payroll.application.statutory_schedule_use_cases import StatutoryScheduleUseCases
from app.payroll.infrastructure.dependencies import get_statutory_schedule_use_cases


router = APIRouter(
    prefix="/payroll/statutory",
    tags=["Payroll statutory schedules"],
    dependencies=[Depends(require_permission("payroll.manage"))],
)

ProgramCode = Literal["SSS", "PHILHEALTH", "PAGIBIG"]
ScheduleState = Literal["DRAFT", "ACTIVE", "RETIRED"]
MoneyAmount = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
]
ContributionRate = Annotated[
    Decimal,
    Field(ge=0, le=1, max_digits=8, decimal_places=6),
]
T = TypeVar("T")


class ContributionScheduleWriteSchema(BaseModel):
    program_code: ProgramCode
    schedule_name: str = Field(min_length=1, max_length=120)
    effective_from: date
    effective_to: date | None = None
    source_reference: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class ContributionScheduleSchema(ContributionScheduleWriteSchema):
    id: UUID
    status: ScheduleState
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime
    updated_by: UUID | None
    row_version: int

    model_config = ConfigDict(from_attributes=True)


class ContributionBracketWriteSchema(BaseModel):
    bracket_number: int = Field(gt=0)
    compensation_min: MoneyAmount
    compensation_max: MoneyAmount | None = None
    contribution_base: MoneyAmount
    employee_rate: ContributionRate
    employer_rate: ContributionRate
    employee_fixed_amount: MoneyAmount
    employer_fixed_amount: MoneyAmount
    employer_additional_fixed_amount: MoneyAmount

    model_config = ConfigDict(extra="forbid")


class ContributionBracketSchema(ContributionBracketWriteSchema):
    id: UUID
    schedule_id: UUID

    model_config = ConfigDict(from_attributes=True)


class WithholdingTaxScheduleWriteSchema(BaseModel):
    schedule_name: str = Field(min_length=1, max_length=120)
    effective_from: date
    effective_to: date | None = None
    tax_exempt_benefit_limit: MoneyAmount
    source_reference: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class WithholdingTaxScheduleSchema(WithholdingTaxScheduleWriteSchema):
    id: UUID
    status: ScheduleState
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime
    updated_by: UUID | None
    row_version: int

    model_config = ConfigDict(from_attributes=True)


class WithholdingTaxBracketWriteSchema(BaseModel):
    bracket_number: int = Field(gt=0)
    annual_income_min: MoneyAmount
    annual_income_max: MoneyAmount | None = None
    base_tax: MoneyAmount
    marginal_rate: ContributionRate
    excess_over: MoneyAmount

    model_config = ConfigDict(extra="forbid")


class WithholdingTaxBracketSchema(WithholdingTaxBracketWriteSchema):
    id: UUID
    schedule_id: UUID

    model_config = ConfigDict(from_attributes=True)


def _actor_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error


async def _execute(action: Awaitable[T]) -> T:
    try:
        return await action
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


def _contribution_schedule_input(
    payload: ContributionScheduleWriteSchema, actor_id: UUID
) -> ContributionScheduleInput:
    return ContributionScheduleInput(
        program_code=payload.program_code,
        schedule_name=payload.schedule_name,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        source_reference=payload.source_reference,
        actor_id=actor_id,
    )


def _tax_schedule_input(
    payload: WithholdingTaxScheduleWriteSchema, actor_id: UUID
) -> WithholdingTaxScheduleInput:
    return WithholdingTaxScheduleInput(
        schedule_name=payload.schedule_name,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        tax_exempt_benefit_limit=payload.tax_exempt_benefit_limit,
        source_reference=payload.source_reference,
        actor_id=actor_id,
    )


def _contribution_bracket_input(
    payload: ContributionBracketWriteSchema,
) -> ContributionBracketInput:
    return ContributionBracketInput(**payload.model_dump())


def _tax_bracket_input(
    payload: WithholdingTaxBracketWriteSchema,
) -> WithholdingTaxBracketInput:
    return WithholdingTaxBracketInput(**payload.model_dump())


async def _audit_change(
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
    "/contribution-schedules",
    response_model=ResponseEnvelope[list[ContributionScheduleSchema]],
)
async def list_contribution_schedules(
    program_code: ProgramCode | None = None,
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await use_cases.list_contribution_schedules(program_code)
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/contribution-schedules",
    response_model=ResponseEnvelope[ContributionScheduleSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_contribution_schedule(
    payload: ContributionScheduleWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.create_contribution_schedule(_contribution_schedule_input(payload, actor_id))
    )
    await _audit_change(
        es_client,
        actor_id=actor_id,
        action="CREATE",
        resource="payroll_contribution_schedule",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/contribution-schedules/{schedule_id}",
    response_model=ResponseEnvelope[ContributionScheduleSchema],
)
async def get_contribution_schedule(
    schedule_id: UUID,
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await _execute(use_cases.get_contribution_schedule(schedule_id))
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/contribution-schedules/{schedule_id}",
    response_model=ResponseEnvelope[ContributionScheduleSchema],
)
async def update_contribution_schedule(
    schedule_id: UUID,
    payload: ContributionScheduleWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.update_contribution_schedule(
            schedule_id, _contribution_schedule_input(payload, actor_id)
        )
    )
    await _audit_change(
        es_client, actor_id=actor_id, action="UPDATE",
        resource="payroll_contribution_schedule", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/contribution-schedules/{schedule_id}",
    response_model=ResponseEnvelope[dict[str, bool]],
)
async def delete_contribution_schedule(
    schedule_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _execute(use_cases.delete_contribution_schedule(schedule_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="DELETE",
        resource="payroll_contribution_schedule", resource_id=schedule_id,
    )
    return ResponseEnvelope(status="success", data={"deleted": True})


@router.post(
    "/contribution-schedules/{schedule_id}/activate",
    response_model=ResponseEnvelope[ContributionScheduleSchema],
)
async def activate_contribution_schedule(
    schedule_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(use_cases.activate_contribution_schedule(schedule_id, actor_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="ACTIVATE",
        resource="payroll_contribution_schedule", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/contribution-schedules/{schedule_id}/retire",
    response_model=ResponseEnvelope[ContributionScheduleSchema],
)
async def retire_contribution_schedule(
    schedule_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(use_cases.retire_contribution_schedule(schedule_id, actor_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="RETIRE",
        resource="payroll_contribution_schedule", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/contribution-schedules/{schedule_id}/brackets",
    response_model=ResponseEnvelope[list[ContributionBracketSchema]],
)
async def list_contribution_brackets(
    schedule_id: UUID,
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await _execute(use_cases.list_contribution_brackets(schedule_id))
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/contribution-schedules/{schedule_id}/brackets",
    response_model=ResponseEnvelope[ContributionBracketSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_contribution_bracket(
    schedule_id: UUID,
    payload: ContributionBracketWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.create_contribution_bracket(
            schedule_id, _contribution_bracket_input(payload)
        )
    )
    await _audit_change(
        es_client, actor_id=actor_id, action="CREATE",
        resource="payroll_contribution_bracket", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/contribution-brackets/{bracket_id}",
    response_model=ResponseEnvelope[ContributionBracketSchema],
)
async def get_contribution_bracket(
    bracket_id: UUID,
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await _execute(use_cases.get_contribution_bracket(bracket_id))
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/contribution-brackets/{bracket_id}",
    response_model=ResponseEnvelope[ContributionBracketSchema],
)
async def update_contribution_bracket(
    bracket_id: UUID,
    payload: ContributionBracketWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.update_contribution_bracket(
            bracket_id, _contribution_bracket_input(payload)
        )
    )
    await _audit_change(
        es_client, actor_id=actor_id, action="UPDATE",
        resource="payroll_contribution_bracket", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/contribution-brackets/{bracket_id}",
    response_model=ResponseEnvelope[dict[str, bool]],
)
async def delete_contribution_bracket(
    bracket_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _execute(use_cases.delete_contribution_bracket(bracket_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="DELETE",
        resource="payroll_contribution_bracket", resource_id=bracket_id,
    )
    return ResponseEnvelope(status="success", data={"deleted": True})


@router.get(
    "/withholding-tax-schedules",
    response_model=ResponseEnvelope[list[WithholdingTaxScheduleSchema]],
)
async def list_withholding_tax_schedules(
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await use_cases.list_withholding_tax_schedules()
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/withholding-tax-schedules",
    response_model=ResponseEnvelope[WithholdingTaxScheduleSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_withholding_tax_schedule(
    payload: WithholdingTaxScheduleWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.create_withholding_tax_schedule(_tax_schedule_input(payload, actor_id))
    )
    await _audit_change(
        es_client, actor_id=actor_id, action="CREATE",
        resource="payroll_withholding_tax_schedule", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/withholding-tax-schedules/{schedule_id}",
    response_model=ResponseEnvelope[WithholdingTaxScheduleSchema],
)
async def get_withholding_tax_schedule(
    schedule_id: UUID,
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await _execute(use_cases.get_withholding_tax_schedule(schedule_id))
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/withholding-tax-schedules/{schedule_id}",
    response_model=ResponseEnvelope[WithholdingTaxScheduleSchema],
)
async def update_withholding_tax_schedule(
    schedule_id: UUID,
    payload: WithholdingTaxScheduleWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.update_withholding_tax_schedule(
            schedule_id, _tax_schedule_input(payload, actor_id)
        )
    )
    await _audit_change(
        es_client, actor_id=actor_id, action="UPDATE",
        resource="payroll_withholding_tax_schedule", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/withholding-tax-schedules/{schedule_id}",
    response_model=ResponseEnvelope[dict[str, bool]],
)
async def delete_withholding_tax_schedule(
    schedule_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _execute(use_cases.delete_withholding_tax_schedule(schedule_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="DELETE",
        resource="payroll_withholding_tax_schedule", resource_id=schedule_id,
    )
    return ResponseEnvelope(status="success", data={"deleted": True})


@router.post(
    "/withholding-tax-schedules/{schedule_id}/activate",
    response_model=ResponseEnvelope[WithholdingTaxScheduleSchema],
)
async def activate_withholding_tax_schedule(
    schedule_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(use_cases.activate_withholding_tax_schedule(schedule_id, actor_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="ACTIVATE",
        resource="payroll_withholding_tax_schedule", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/withholding-tax-schedules/{schedule_id}/retire",
    response_model=ResponseEnvelope[WithholdingTaxScheduleSchema],
)
async def retire_withholding_tax_schedule(
    schedule_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(use_cases.retire_withholding_tax_schedule(schedule_id, actor_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="RETIRE",
        resource="payroll_withholding_tax_schedule", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/withholding-tax-schedules/{schedule_id}/brackets",
    response_model=ResponseEnvelope[list[WithholdingTaxBracketSchema]],
)
async def list_withholding_tax_brackets(
    schedule_id: UUID,
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await _execute(use_cases.list_withholding_tax_brackets(schedule_id))
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/withholding-tax-schedules/{schedule_id}/brackets",
    response_model=ResponseEnvelope[WithholdingTaxBracketSchema],
    status_code=status.HTTP_201_CREATED,
)
async def create_withholding_tax_bracket(
    schedule_id: UUID,
    payload: WithholdingTaxBracketWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.create_withholding_tax_bracket(
            schedule_id, _tax_bracket_input(payload)
        )
    )
    await _audit_change(
        es_client, actor_id=actor_id, action="CREATE",
        resource="payroll_withholding_tax_bracket", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/withholding-tax-brackets/{bracket_id}",
    response_model=ResponseEnvelope[WithholdingTaxBracketSchema],
)
async def get_withholding_tax_bracket(
    bracket_id: UUID,
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
):
    result = await _execute(use_cases.get_withholding_tax_bracket(bracket_id))
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/withholding-tax-brackets/{bracket_id}",
    response_model=ResponseEnvelope[WithholdingTaxBracketSchema],
)
async def update_withholding_tax_bracket(
    bracket_id: UUID,
    payload: WithholdingTaxBracketWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await _execute(
        use_cases.update_withholding_tax_bracket(
            bracket_id, _tax_bracket_input(payload)
        )
    )
    await _audit_change(
        es_client, actor_id=actor_id, action="UPDATE",
        resource="payroll_withholding_tax_bracket", resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/withholding-tax-brackets/{bracket_id}",
    response_model=ResponseEnvelope[dict[str, bool]],
)
async def delete_withholding_tax_bracket(
    bracket_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: StatutoryScheduleUseCases = Depends(get_statutory_schedule_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _execute(use_cases.delete_withholding_tax_bracket(bracket_id))
    await _audit_change(
        es_client, actor_id=actor_id, action="DELETE",
        resource="payroll_withholding_tax_bracket", resource_id=bracket_id,
    )
    return ResponseEnvelope(status="success", data={"deleted": True})
