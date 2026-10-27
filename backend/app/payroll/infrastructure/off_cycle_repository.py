from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_groups.infrastructure.db_model import PayrollGroupModel
from app.payroll.application.off_cycle_inputs import (
    NewOffCycleRun,
    OffCycleEmployee,
    OffCycleLineDraft,
    OffCycleRunTransition,
    ThirteenthMonthPayable,
    ThirteenthMonthRunSummary,
)
from app.payroll.domain.entities.benefits import BenefitType
from app.payroll.domain.entities.off_cycle import (
    OffCyclePayrollLine,
    OffCyclePayrollRun,
    OffCycleRunStatus,
)
from app.payroll.domain.services.off_cycle_tax import OffCycleTaxContext, OffCycleYtd
from app.payroll.infrastructure.benefit_repository import _benefit_type_entity
from app.payroll.infrastructure.db_model import (
    BenefitTypeModel,
    GrossPayResultModel,
    GrossPayRunModel,
    OffCyclePayrollLineModel,
    OffCyclePayrollRunModel,
    ThirteenthMonthResultModel,
    ThirteenthMonthRunModel,
    WithholdingTaxBracketModel,
    WithholdingTaxScheduleModel,
)
from app.payroll.infrastructure.repository import (
    _current_opening_ytd_balances,
    _tax_bracket_entity,
)


# Submitted and approved runs reserve exemption room and tax ahead of payment so
# two concurrent batches cannot both use the same shared exemption limit.
YTD_COUNTED_STATUSES = ("PENDING", "APPROVED", "PAID")


def _employee_name(model: EmployeeModel) -> str:
    return " ".join(
        part
        for part in (model.first_name, model.middle_name, model.last_name, model.suffix)
        if part
    )


def _session(uow: GenUnitOfWork) -> AsyncSession:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return uow.session


async def _load_run_entity(session: AsyncSession, model: OffCyclePayrollRunModel) -> OffCyclePayrollRun:
    benefit_type = await session.get(BenefitTypeModel, model.benefit_type_id)
    line_rows = (
        await session.execute(
            select(OffCyclePayrollLineModel, EmployeeModel)
            .join(EmployeeModel, EmployeeModel.id == OffCyclePayrollLineModel.employee_id)
            .where(OffCyclePayrollLineModel.run_id == model.id)
            .order_by(OffCyclePayrollLineModel.employee_no)
        )
    ).all()
    return _run_entity(
        model,
        benefit_type,
        tuple(_line_entity(line, _employee_name(employee)) for line, employee in line_rows),
    )


def _line_entity(model: OffCyclePayrollLineModel, employee_name: str) -> OffCyclePayrollLine:
    return OffCyclePayrollLine(
        id=model.id,
        run_id=model.run_id,
        employee_id=model.employee_id,
        employee_no=model.employee_no,
        employee_name=employee_name,
        benefit_code=model.benefit_code,
        benefit_name=model.benefit_name,
        category=model.category,  # type: ignore[arg-type]
        tax_treatment=model.tax_treatment,  # type: ignore[arg-type]
        withholding_timing=model.withholding_timing,  # type: ignore[arg-type]
        amount=Decimal(model.amount),
        taxable_amount=Decimal(model.taxable_amount),
        exempt_limited_amount=Decimal(model.exempt_limited_amount),
        withholding_tax=Decimal(model.withholding_tax),
        net_amount=Decimal(model.net_amount),
        notes=model.notes,
        thirteenth_month_result_id=model.thirteenth_month_result_id,
    )


def _run_entity(
    model: OffCyclePayrollRunModel,
    benefit_type: BenefitTypeModel | None,
    lines: tuple[OffCyclePayrollLine, ...],
) -> OffCyclePayrollRun:
    return OffCyclePayrollRun(
        id=model.id,
        company_id=model.company_id,
        payroll_group_id=model.payroll_group_id,
        benefit_type_id=model.benefit_type_id,
        benefit_code=benefit_type.code if benefit_type else "",
        benefit_name=benefit_type.name if benefit_type else "",
        run_type=model.run_type,  # type: ignore[arg-type]
        status=model.status,  # type: ignore[arg-type]
        proposed_payment_date=model.proposed_payment_date,
        actual_payment_date=model.actual_payment_date,
        notes=model.notes,
        rejection_reason=model.rejection_reason,
        created_by=model.created_by,
        created_at=model.created_at,
        submitted_at=model.submitted_at,
        approved_by=model.approved_by,
        approved_at=model.approved_at,
        paid_by=model.paid_by,
        paid_at=model.paid_at,
        thirteenth_month_run_id=model.thirteenth_month_run_id,
        lines=lines,
    )


async def _locked_run(session: AsyncSession, run_id: UUID) -> OffCyclePayrollRunModel:
    model = await session.scalar(
        select(OffCyclePayrollRunModel)
        .where(OffCyclePayrollRunModel.id == run_id)
        .with_for_update()
    )
    if model is None:
        raise LookupError("Off-cycle payroll run not found.")
    return model


def _reserved_thirteenth_month_result_ids(exclude_run_id: UUID | None = None):
    query = (
        select(OffCyclePayrollLineModel.thirteenth_month_result_id)
        .join(OffCyclePayrollRunModel, OffCyclePayrollRunModel.id == OffCyclePayrollLineModel.run_id)
        .where(
            OffCyclePayrollLineModel.thirteenth_month_result_id.is_not(None),
            OffCyclePayrollRunModel.status != "REJECTED",
        )
    )
    if exclude_run_id is not None:
        query = query.where(OffCyclePayrollRunModel.id != exclude_run_id)
    return query


class SqlAlchemyOffCyclePayrollRepository:
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def list_runs(
        self,
        *,
        company_id: UUID | None = None,
        payroll_group_id: UUID | None = None,
        status: OffCycleRunStatus | None = None,
    ) -> list[OffCyclePayrollRun]:
        async with self._uow as uow:
            session = _session(uow)
            query = select(OffCyclePayrollRunModel).order_by(
                OffCyclePayrollRunModel.created_at.desc()
            )
            if company_id is not None:
                query = query.where(OffCyclePayrollRunModel.company_id == company_id)
            if payroll_group_id is not None:
                query = query.where(OffCyclePayrollRunModel.payroll_group_id == payroll_group_id)
            if status is not None:
                query = query.where(OffCyclePayrollRunModel.status == status)
            models = list((await session.scalars(query.limit(200))).all())
            return [await _load_run_entity(session, model) for model in models]

    async def get_run(self, run_id: UUID) -> OffCyclePayrollRun:
        async with self._uow as uow:
            session = _session(uow)
            model = await session.get(OffCyclePayrollRunModel, run_id)
            if model is None:
                raise LookupError("Off-cycle payroll run not found.")
            return await _load_run_entity(session, model)

    async def get_payroll_group_company_id(self, payroll_group_id: UUID) -> UUID:
        async with self._uow as uow:
            group = await _session(uow).get(PayrollGroupModel, payroll_group_id)
            if group is None:
                raise LookupError("Payroll group not found.")
            return group.company_id

    async def get_benefit_type(self, benefit_type_id: UUID) -> BenefitType:
        async with self._uow as uow:
            model = await _session(uow).get(BenefitTypeModel, benefit_type_id)
            if model is None:
                raise LookupError("Benefit type not found.")
            return _benefit_type_entity(model)

    async def find_group_employees(
        self, payroll_group_id: UUID, employee_nos: Sequence[str]
    ) -> dict[str, OffCycleEmployee]:
        normalized = list({value.strip().upper() for value in employee_nos if value.strip()})
        if not normalized:
            return {}
        async with self._uow as uow:
            session = _session(uow)
            assigned = exists().where(
                EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                EmploymentAssignmentModel.payroll_group_id == payroll_group_id,
                EmploymentAssignmentModel.is_active.is_(True),
            )
            employees = await session.scalars(
                select(EmployeeModel).where(
                    func.upper(EmployeeModel.employee_no).in_(normalized),
                    assigned,
                )
            )
            return {
                model.employee_no.upper(): OffCycleEmployee(
                    employee_id=model.id,
                    employee_no=model.employee_no,
                    employee_name=_employee_name(model),
                )
                for model in employees
            }

    async def list_thirteenth_month_runs(
        self, company_id: UUID
    ) -> list[ThirteenthMonthRunSummary]:
        async with self._uow as uow:
            session = _session(uow)
            rows = await session.execute(
                select(
                    ThirteenthMonthRunModel,
                    func.count(ThirteenthMonthResultModel.id),
                )
                .outerjoin(
                    ThirteenthMonthResultModel,
                    ThirteenthMonthResultModel.run_id == ThirteenthMonthRunModel.id,
                )
                .where(
                    ThirteenthMonthRunModel.company_id == company_id,
                    ThirteenthMonthRunModel.is_current.is_(True),
                )
                .group_by(ThirteenthMonthRunModel.id)
                .order_by(ThirteenthMonthRunModel.tax_year.desc())
            )
            return [
                ThirteenthMonthRunSummary(
                    id=model.id,
                    tax_year=model.tax_year,
                    covered_period_from=model.covered_period_from,
                    covered_period_to=model.covered_period_to,
                    calculated_at=model.calculated_at,
                    result_count=int(result_count or 0),
                )
                for model, result_count in rows
            ]

    async def list_thirteenth_month_payables(
        self, thirteenth_month_run_id: UUID, payroll_group_id: UUID
    ) -> list[ThirteenthMonthPayable]:
        async with self._uow as uow:
            session = _session(uow)
            run = await session.get(ThirteenthMonthRunModel, thirteenth_month_run_id)
            group = await session.get(PayrollGroupModel, payroll_group_id)
            if run is None or group is None:
                raise LookupError("13th-month run or payroll group not found.")
            if run.company_id != group.company_id:
                raise ValueError("The 13th-month run belongs to a different company.")
            if not run.is_current:
                raise ValueError(
                    "This 13th-month run was superseded by a newer calculation. Select the current run."
                )
            assigned = exists().where(
                EmploymentAssignmentModel.employee_id == ThirteenthMonthResultModel.employee_id,
                EmploymentAssignmentModel.payroll_group_id == payroll_group_id,
                EmploymentAssignmentModel.is_active.is_(True),
            )
            results = await session.scalars(
                select(ThirteenthMonthResultModel)
                .where(
                    ThirteenthMonthResultModel.run_id == thirteenth_month_run_id,
                    assigned,
                    ThirteenthMonthResultModel.id.not_in(_reserved_thirteenth_month_result_ids()),
                )
                .order_by(ThirteenthMonthResultModel.employee_no)
            )
            return [
                ThirteenthMonthPayable(
                    result_id=item.id,
                    employee_id=item.employee_id,
                    employee_no=item.employee_no,
                    employee_name=item.employee_name,
                    amount=Decimal(item.thirteenth_month_pay),
                )
                for item in results
            ]

    async def load_tax_context(self, as_of: date) -> OffCycleTaxContext:
        async with self._uow as uow:
            session = _session(uow)
            schedules = list(
                (
                    await session.scalars(
                        select(WithholdingTaxScheduleModel).where(
                            WithholdingTaxScheduleModel.status == "ACTIVE",
                            WithholdingTaxScheduleModel.effective_from <= as_of,
                            or_(
                                WithholdingTaxScheduleModel.effective_to.is_(None),
                                WithholdingTaxScheduleModel.effective_to >= as_of,
                            ),
                        )
                    )
                ).all()
            )
            if len(schedules) != 1:
                raise ValueError(
                    "Exactly one active withholding-tax schedule must cover the payment date."
                )
            schedule = schedules[0]
            brackets = tuple(
                _tax_bracket_entity(item)
                for item in await session.scalars(
                    select(WithholdingTaxBracketModel)
                    .where(WithholdingTaxBracketModel.schedule_id == schedule.id)
                    .order_by(WithholdingTaxBracketModel.bracket_number)
                )
            )
            if not brackets:
                raise ValueError("The active withholding-tax schedule has no brackets.")
            return OffCycleTaxContext(
                calculation_basis=schedule.calculation_basis,  # type: ignore[arg-type]
                brackets=brackets,
                tax_exempt_benefit_limit=Decimal(schedule.tax_exempt_benefit_limit),
            )

    async def load_ytd(
        self,
        *,
        company_id: UUID,
        employee_ids: Sequence[UUID],
        as_of: date,
        exclude_run_id: UUID | None = None,
        created_before: datetime | None = None,
    ) -> dict[UUID, OffCycleYtd]:
        employee_ids = list(dict.fromkeys(employee_ids))
        totals: dict[UUID, list[Decimal]] = {
            employee_id: [Decimal(0), Decimal(0), Decimal(0)] for employee_id in employee_ids
        }
        if not employee_ids:
            return {}
        year_start = date(as_of.year, 1, 1)
        async with self._uow as uow:
            session = _session(uow)
            openings = await _current_opening_ytd_balances(session, employee_ids, as_of.year)
            for employee_id, opening in openings.items():
                totals[employee_id][0] += Decimal(opening.taxable_income)
                totals[employee_id][1] += Decimal(opening.tax_withheld)
                totals[employee_id][2] += Decimal(opening.exempt_limited_benefits)

            regular_rows = await session.execute(
                select(
                    GrossPayResultModel.employee_id,
                    func.coalesce(func.sum(GrossPayResultModel.taxable_income), 0),
                    func.coalesce(func.sum(GrossPayResultModel.withholding_tax), 0),
                    func.coalesce(func.sum(GrossPayResultModel.exempt_limited_benefit_amount), 0),
                )
                .join(GrossPayRunModel, GrossPayRunModel.id == GrossPayResultModel.run_id)
                .join(PayrollCutoffModel, PayrollCutoffModel.id == GrossPayRunModel.cutoff_id)
                .join(PayrollGroupModel, PayrollGroupModel.id == PayrollCutoffModel.payroll_group_id)
                .where(
                    GrossPayRunModel.is_current.is_(True),
                    GrossPayResultModel.status == "READY",
                    PayrollGroupModel.company_id == company_id,
                    PayrollCutoffModel.period_end >= year_start,
                    PayrollCutoffModel.period_end <= as_of,
                    GrossPayResultModel.employee_id.in_(employee_ids),
                )
                .group_by(GrossPayResultModel.employee_id)
            )
            for employee_id, taxable, tax, limited in regular_rows:
                totals[employee_id][0] += Decimal(taxable)
                totals[employee_id][1] += Decimal(tax)
                totals[employee_id][2] += Decimal(limited)

            effective_date = func.coalesce(
                OffCyclePayrollRunModel.actual_payment_date,
                OffCyclePayrollRunModel.proposed_payment_date,
            )
            if created_before is None:
                ordering = effective_date <= as_of
            else:
                ordering = or_(
                    effective_date < as_of,
                    and_(
                        effective_date == as_of,
                        OffCyclePayrollRunModel.created_at < created_before,
                    ),
                )
            off_cycle_query = (
                select(
                    OffCyclePayrollLineModel.employee_id,
                    func.coalesce(func.sum(OffCyclePayrollLineModel.taxable_amount), 0),
                    func.coalesce(func.sum(OffCyclePayrollLineModel.withholding_tax), 0),
                    func.coalesce(func.sum(OffCyclePayrollLineModel.exempt_limited_amount), 0),
                )
                .join(
                    OffCyclePayrollRunModel,
                    OffCyclePayrollRunModel.id == OffCyclePayrollLineModel.run_id,
                )
                .where(
                    OffCyclePayrollRunModel.company_id == company_id,
                    OffCyclePayrollLineModel.employee_id.in_(employee_ids),
                    effective_date >= year_start,
                    ordering,
                    OffCyclePayrollRunModel.status.in_(YTD_COUNTED_STATUSES),
                )
                .group_by(OffCyclePayrollLineModel.employee_id)
            )
            if exclude_run_id is not None:
                off_cycle_query = off_cycle_query.where(
                    OffCyclePayrollRunModel.id != exclude_run_id
                )
            for employee_id, taxable, tax, limited in await session.execute(off_cycle_query):
                totals[employee_id][0] += Decimal(taxable)
                totals[employee_id][1] += Decimal(tax)
                totals[employee_id][2] += Decimal(limited)

        return {
            employee_id: OffCycleYtd(
                taxable_income=values[0],
                withholding_tax=values[1],
                exempt_limited_benefits=values[2],
            )
            for employee_id, values in totals.items()
        }

    async def create_run(self, data: NewOffCycleRun) -> OffCyclePayrollRun:
        async with self._uow as uow:
            session = _session(uow)
            benefit_type = await session.get(BenefitTypeModel, data.benefit_type_id)
            if benefit_type is None:
                raise LookupError("Benefit type not found.")
            result_ids = [
                line.thirteenth_month_result_id
                for line in data.lines
                if line.thirteenth_month_result_id is not None
            ]
            if result_ids:
                already_reserved = await session.scalar(
                    select(func.count()).select_from(
                        _reserved_thirteenth_month_result_ids()
                        .where(OffCyclePayrollLineModel.thirteenth_month_result_id.in_(result_ids))
                        .subquery()
                    )
                )
                if already_reserved:
                    raise ValueError(
                        "Some 13th-month results are already in another off-cycle run. "
                        "Reject or delete that run first."
                    )
            run = OffCyclePayrollRunModel(
                company_id=data.company_id,
                payroll_group_id=data.payroll_group_id,
                benefit_type_id=data.benefit_type_id,
                thirteenth_month_run_id=data.thirteenth_month_run_id,
                run_type=data.run_type,
                proposed_payment_date=data.proposed_payment_date,
                status="DRAFT",
                notes=data.notes,
                created_by=data.created_by,
            )
            session.add(run)
            await session.flush()
            for line in data.lines:
                session.add(
                    OffCyclePayrollLineModel(
                        run_id=run.id,
                        employee_id=line.employee_id,
                        thirteenth_month_result_id=line.thirteenth_month_result_id,
                        employee_no=line.employee_no,
                        benefit_code=benefit_type.code,
                        benefit_name=benefit_type.name,
                        category=benefit_type.category,
                        tax_treatment=benefit_type.tax_treatment,
                        withholding_timing=benefit_type.withholding_timing,
                        amount=line.amount,
                        taxable_amount=line.taxable_amount,
                        exempt_limited_amount=line.exempt_limited_amount,
                        withholding_tax=line.withholding_tax,
                        net_amount=line.net_amount,
                        notes=line.notes,
                    )
                )
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError(
                    "The off-cycle run could not be saved because an employee appears more than once."
                ) from error
            await session.refresh(run)
            return await _load_run_entity(session, run)

    async def replace_lines(
        self,
        run_id: UUID,
        expected_status: OffCycleRunStatus,
        lines: Sequence[OffCycleLineDraft],
    ) -> OffCyclePayrollRun:
        async with self._uow as uow:
            session = _session(uow)
            run = await _locked_run(session, run_id)
            if run.status != expected_status:
                raise ValueError("This off-cycle run was changed by another user. Refresh and try again.")
            by_employee = {line.employee_id: line for line in lines}
            existing = list(
                (
                    await session.scalars(
                        select(OffCyclePayrollLineModel).where(
                            OffCyclePayrollLineModel.run_id == run_id
                        )
                    )
                ).all()
            )
            if {item.employee_id for item in existing} != set(by_employee):
                raise ValueError("Recalculated lines do not match this off-cycle run's employees.")
            for item in existing:
                line = by_employee[item.employee_id]
                item.amount = line.amount
                item.taxable_amount = line.taxable_amount
                item.exempt_limited_amount = line.exempt_limited_amount
                item.withholding_tax = line.withholding_tax
                item.net_amount = line.net_amount
            await session.flush()
            return await _load_run_entity(session, run)

    async def transition_run(
        self, run_id: UUID, transition: OffCycleRunTransition
    ) -> OffCyclePayrollRun:
        async with self._uow as uow:
            session = _session(uow)
            run = await _locked_run(session, run_id)
            if run.status != transition.expected_status:
                raise ValueError("This off-cycle run was changed by another user. Refresh and try again.")
            run.status = transition.new_status
            if transition.new_status == "PENDING":
                run.submitted_at = transition.occurred_at
                run.rejection_reason = None
            elif transition.new_status == "APPROVED":
                run.approved_by = transition.actor_id
                run.approved_at = transition.occurred_at
            elif transition.new_status == "REJECTED":
                run.rejection_reason = transition.rejection_reason
                run.approved_by = None
                run.approved_at = None
            elif transition.new_status == "PAID":
                run.paid_by = transition.actor_id
                run.paid_at = transition.occurred_at
                run.actual_payment_date = transition.actual_payment_date
            await session.flush()
            return await _load_run_entity(session, run)

    async def delete_run(self, run_id: UUID, allowed_statuses: frozenset[str]) -> None:
        async with self._uow as uow:
            session = _session(uow)
            run = await _locked_run(session, run_id)
            if run.status not in allowed_statuses:
                raise ValueError("This off-cycle run can no longer be deleted.")
            await session.execute(
                delete(OffCyclePayrollLineModel).where(OffCyclePayrollLineModel.run_id == run_id)
            )
            await session.delete(run)
            await session.flush()
