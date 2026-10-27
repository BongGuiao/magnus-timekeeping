from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.payroll.application.loan_inputs import (
    EmployeeLoanInput,
    RestructureEmployeeLoanInput,
)
from app.payroll.domain.entities.loans import (
    EmployeeLoan,
    EmployeeLoanRepayment,
    restructured_principal,
)
from app.payroll.infrastructure.loan_db_model import (
    EmployeeLoanModel,
    EmployeeLoanRepaymentModel,
)


def _entity(
    model: EmployeeLoanModel,
    repayments: tuple[EmployeeLoanRepayment, ...] = (),
) -> EmployeeLoan:
    return EmployeeLoan(
        id=model.id,
        employee_id=model.employee_id,
        payroll_group_id=model.payroll_group_id,
        reference_number=model.reference_number,
        principal_amount=Decimal(model.principal_amount),
        installment_amount=Decimal(model.installment_amount),
        schedule=model.schedule,
        effective_from=model.effective_from,
        outstanding_balance=Decimal(model.outstanding_balance),
        status=model.status,
        previous_loan_id=model.previous_loan_id,
        created_at=model.created_at,
        repayments=repayments,
    )


class SqlAlchemyLoanRepository:
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def list_employee_loans(self, payroll_group_id: UUID) -> list[EmployeeLoan]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = list((await session.scalars(
                select(EmployeeLoanModel)
                .where(EmployeeLoanModel.payroll_group_id == payroll_group_id)
                .order_by(EmployeeLoanModel.created_at.desc(), EmployeeLoanModel.reference_number)
            )).all())
            loan_ids = [model.id for model in models]
            repayments_by_loan: dict[UUID, list[EmployeeLoanRepayment]] = {
                loan_id: [] for loan_id in loan_ids
            }
            if loan_ids:
                repayment_rows = await session.execute(
                    select(EmployeeLoanRepaymentModel, PayrollCutoffModel.cutoff_code)
                    .join(
                        PayrollCutoffModel,
                        PayrollCutoffModel.id == EmployeeLoanRepaymentModel.cutoff_id,
                    )
                    .where(EmployeeLoanRepaymentModel.loan_id.in_(loan_ids))
                    .order_by(EmployeeLoanRepaymentModel.created_at, EmployeeLoanRepaymentModel.id)
                )
                for repayment, cutoff_code in repayment_rows:
                    repayments_by_loan[repayment.loan_id].append(
                        EmployeeLoanRepayment(
                            id=repayment.id,
                            loan_id=repayment.loan_id,
                            cutoff_id=repayment.cutoff_id,
                            gross_pay_run_id=repayment.gross_pay_run_id,
                            amount=Decimal(repayment.amount),
                            created_at=repayment.created_at,
                            cutoff_code=cutoff_code,
                        )
                    )
            return [
                _entity(model, tuple(repayments_by_loan[model.id]))
                for model in models
            ]

    async def create_employee_loan(self, data: EmployeeLoanInput) -> EmployeeLoan:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = EmployeeLoanModel(
                employee_id=data.employee_id,
                payroll_group_id=data.payroll_group_id,
                reference_number=data.reference_number.strip(),
                principal_amount=data.principal_amount,
                installment_amount=data.installment_amount,
                schedule=data.schedule,
                effective_from=data.effective_from,
                outstanding_balance=data.principal_amount,
                created_by=data.actor_id,
            )
            session.add(model)
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError("Loan reference number already exists.") from error
            return _entity(model)

    async def retire_employee_loan(self, loan_id: UUID) -> EmployeeLoan:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await self._get_locked(session, loan_id)
            if model.status != "ACTIVE":
                raise ValueError("Only an active loan can be retired.")
            model.status = "RETIRED"
            await session.flush()
            return _entity(model)

    async def restructure_employee_loan(
        self, loan_id: UUID, data: RestructureEmployeeLoanInput
    ) -> EmployeeLoan:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            previous = await self._get_locked(session, loan_id)
            if previous.status != "ACTIVE":
                raise ValueError("Only an active loan can be restructured.")
            principal = restructured_principal(
                Decimal(previous.outstanding_balance),
                data.additional_principal,
            )
            previous.status = "RETIRED"
            replacement = EmployeeLoanModel(
                employee_id=previous.employee_id,
                payroll_group_id=previous.payroll_group_id,
                reference_number=data.reference_number.strip(),
                principal_amount=principal,
                installment_amount=data.installment_amount,
                schedule=data.schedule,
                effective_from=data.effective_from,
                outstanding_balance=principal,
                previous_loan_id=previous.id,
                created_by=data.actor_id,
            )
            session.add(replacement)
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError("Loan reference number already exists.") from error
            return _entity(replacement)

    @staticmethod
    async def _get_locked(session, loan_id: UUID) -> EmployeeLoanModel:
        model = await session.scalar(
            select(EmployeeLoanModel)
            .where(EmployeeLoanModel.id == loan_id)
            .with_for_update()
        )
        if model is None:
            raise LookupError("Employee loan not found.")
        return model
