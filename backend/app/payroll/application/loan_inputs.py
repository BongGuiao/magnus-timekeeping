from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.payroll.domain.entities.loans import LoanSchedule


@dataclass(frozen=True)
class EmployeeLoanInput:
    employee_id: UUID
    payroll_group_id: UUID
    reference_number: str
    principal_amount: Decimal
    installment_amount: Decimal
    schedule: LoanSchedule
    effective_from: date
    actor_id: UUID


@dataclass(frozen=True)
class RestructureEmployeeLoanInput:
    reference_number: str
    additional_principal: Decimal
    installment_amount: Decimal
    schedule: LoanSchedule
    effective_from: date
    actor_id: UUID
