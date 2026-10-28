from calendar import monthrange
from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.payroll.infrastructure.loan_db_model import (
    EmployeeLoanModel,
    EmployeeLoanRepaymentModel,
)
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.payroll_groups.infrastructure.db_model import PayrollGroupModel
from app.payroll.domain.entities.gross_payroll import (
    Compensation,
    CutoffEmployeeTime,
    CutoffPayrollData,
    EarningRule,
    GrossPayLine,
    GrossPayResult,
    GrossPayRun,
    PayrollApprovalPermissionError,
    PayrollCutoffLockState,
    ThirteenthMonthResult,
    ThirteenthMonthRun,
    PayrollBenefitLine,
    PayrollContributionLine,
    PayrollGroupPolicy,
)
from app.payroll.domain.entities.benefits import (
    CutoffBenefit,
    is_benefit_due,
    is_employee_deduction_due,
)
from app.payroll.domain.entities.loans import loan_due_this_cutoff, loan_installment_due
from app.payroll.domain.entities.net_payroll import NetPayrollInputs, OpeningYtdBalance
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    ContributionProgram,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
)
from app.payroll.domain.services.net_payroll import REQUIRED_CONTRIBUTION_PROGRAMS
from app.payroll.domain.services.thirteenth_month import calculate_thirteenth_month_amounts
from app.payroll.domain.assignment_coverage import require_exact_assignment_coverage
from app.payroll.infrastructure.db_model import (
    EmployeeCompensationModel,
    BenefitTypeModel,
    CutoffBenefitModel,
    EmployeeBenefitEntitlementModel,
    EmployeeBenefitDeductionModel,
    GrossPayResultModel,
    GrossPayRunModel,
    OffCyclePayrollLineModel,
    OffCyclePayrollRunModel,
    PayrollOpeningYtdBalanceModel,
    PayrollSystemParametersModel,
    ThirteenthMonthResultModel,
    ThirteenthMonthRunModel,
    PayrollEarningRuleModel,
    StatutoryContributionBracketModel,
    StatutoryContributionScheduleModel,
    WithholdingTaxBracketModel,
    WithholdingTaxScheduleModel,
)


def _compensation_entity(model: EmployeeCompensationModel) -> Compensation:
    return Compensation(
        id=model.id,
        employee_id=model.employee_id,
        payroll_group_id=model.payroll_group_id,
        base_rate=Decimal(model.base_rate),
        currency=model.currency,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        is_active=model.is_active,
    )


def _run_entity(
    model: GrossPayRunModel,
    result_models: list[GrossPayResultModel],
) -> GrossPayRun:
    return GrossPayRun(
        id=model.id,
        cutoff_id=model.cutoff_id,
        calculation_version=model.calculation_version,
        calculated_at=model.calculated_at,
        calculated_by=model.calculated_by,
        results=tuple(
            GrossPayResult(
                employee_id=result.employee_id,
                cutoff_result_id=result.cutoff_result_id,
                currency=result.currency,
                base_rate=Decimal(result.base_rate) if result.base_rate is not None else None,
                gross_amount=Decimal(result.gross_amount) if result.gross_amount is not None else None,
                status=result.status,
                hold_reason=result.hold_reason,
                lines=tuple(
                    GrossPayLine(
                        component_code=line["component_code"],
                        minutes=int(line["minutes"]),
                        multiplier=Decimal(line["multiplier"]),
                        amount=Decimal(line["amount"]),
                    )
                    for line in result.earning_lines
                ),
                source_minutes={key: int(value) for key, value in result.source_minutes.items()},
                gross_status=result.gross_status or result.status,
                cash_benefit_amount=(
                    Decimal(result.cash_benefit_amount)
                    if result.cash_benefit_amount is not None else None
                ),
                non_cash_benefit_amount=(
                    Decimal(result.non_cash_benefit_amount)
                    if result.non_cash_benefit_amount is not None else None
                ),
                employee_benefit_deductions=(
                    Decimal(result.employee_benefit_deductions)
                    if result.employee_benefit_deductions is not None else None
                ),
                exempt_limited_benefit_amount=(
                    Decimal(result.exempt_limited_benefit_amount)
                    if result.exempt_limited_benefit_amount is not None else None
                ),
                taxable_income=(
                    Decimal(result.taxable_income) if result.taxable_income is not None else None
                ),
                employee_contributions=(
                    Decimal(result.employee_contributions)
                    if result.employee_contributions is not None else None
                ),
                employer_contributions=(
                    Decimal(result.employer_contributions)
                    if result.employer_contributions is not None else None
                ),
                withholding_tax=(
                    Decimal(result.withholding_tax) if result.withholding_tax is not None else None
                ),
                net_amount=Decimal(result.net_amount) if result.net_amount is not None else None,
                benefit_lines=tuple(
                    PayrollBenefitLine(
                        benefit_code=line["benefit_code"],
                        benefit_name=line["benefit_name"],
                        category=line["category"],
                        tax_treatment=line["tax_treatment"],
                        amount=Decimal(line["amount"]),
                        withholding_timing=line.get("withholding_timing", "PAY_PERIOD"),
                        loan_id=UUID(line["loan_id"]) if line.get("loan_id") else None,
                    )
                    for line in (result.benefit_lines or [])
                ),
                contribution_lines=tuple(
                    PayrollContributionLine(
                        program_code=line["program_code"],
                        employee_amount=Decimal(line["employee_amount"]),
                        employer_amount=Decimal(line["employer_amount"]),
                    )
                    for line in (result.contribution_lines or [])
                ),
            )
            for result in result_models
        ),
    )


async def _company_system_parameters(
    session: AsyncSession, company_id: UUID
) -> PayrollSystemParametersModel:
    await session.execute(
        pg_insert(PayrollSystemParametersModel)
        .values(company_id=company_id)
        .on_conflict_do_nothing(index_elements=[PayrollSystemParametersModel.company_id])
    )
    parameters = await session.get(PayrollSystemParametersModel, company_id)
    if parameters is None:
        raise RuntimeError("Payroll system parameters could not be initialized for this company.")
    return parameters


async def _prior_first_half_contributions(
    session: AsyncSession,
    cutoff: PayrollCutoffModel,
    employee_ids: Sequence[UUID],
) -> tuple[
    dict[UUID, dict[ContributionProgram, Decimal]],
    dict[UUID, dict[ContributionProgram, Decimal]],
]:
    employee_amounts: dict[UUID, dict[ContributionProgram, Decimal]] = {
        employee_id: {code: Decimal(0) for code in REQUIRED_CONTRIBUTION_PROGRAMS}
        for employee_id in employee_ids
    }
    employer_amounts: dict[UUID, dict[ContributionProgram, Decimal]] = {
        employee_id: {code: Decimal(0) for code in REQUIRED_CONTRIBUTION_PROGRAMS}
        for employee_id in employee_ids
    }
    if cutoff.cutoff_half != "SECOND_HALF":
        return employee_amounts, employer_amounts

    loaded_employees: set[UUID] = set()
    for result in await session.scalars(
        select(GrossPayResultModel)
        .join(GrossPayRunModel, GrossPayRunModel.id == GrossPayResultModel.run_id)
        .join(PayrollCutoffModel, PayrollCutoffModel.id == GrossPayRunModel.cutoff_id)
        .where(
            GrossPayRunModel.is_current.is_(True),
            GrossPayResultModel.employee_id.in_(employee_ids),
            GrossPayResultModel.status == "READY",
            PayrollCutoffModel.payroll_group_id == cutoff.payroll_group_id,
            PayrollCutoffModel.is_active.is_(True),
            PayrollCutoffModel.cutoff_half == "FIRST_HALF",
            PayrollCutoffModel.period_end < cutoff.period_start,
            PayrollCutoffModel.id != cutoff.id,
        )
        .order_by(
            PayrollCutoffModel.period_end.desc(),
            PayrollCutoffModel.period_start.desc(),
            PayrollCutoffModel.cutoff_code.desc(),
        )
    ):
        if result.employee_id in loaded_employees:
            continue
        loaded_employees.add(result.employee_id)
        for line in result.contribution_lines or []:
            code = line["program_code"]
            if code in employee_amounts[result.employee_id]:
                employee_amounts[result.employee_id][code] += Decimal(line["employee_amount"])
                employer_amounts[result.employee_id][code] += Decimal(line["employer_amount"])
    return employee_amounts, employer_amounts


def _thirteenth_month_run_entity(
    model: ThirteenthMonthRunModel,
    result_models: list[ThirteenthMonthResultModel],
) -> ThirteenthMonthRun:
    if model.covered_period_from is None or model.covered_period_to is None:
        raise RuntimeError("The 13th-month calculation is missing its covered cutoff dates.")
    return ThirteenthMonthRun(
        id=model.id,
        tax_year=model.tax_year,
        covered_period_from=model.covered_period_from,
        covered_period_to=model.covered_period_to,
        calculated_at=model.calculated_at,
        calculated_by=model.calculated_by,
        results=tuple(
            ThirteenthMonthResult(
                employee_id=item.employee_id,
                employee_no=item.employee_no,
                employee_name=item.employee_name,
                basic_salary_earned=Decimal(item.basic_salary_earned),
                thirteenth_month_pay=Decimal(item.thirteenth_month_pay),
                tax_exempt_amount=Decimal(item.tax_exempt_amount),
                taxable_amount=Decimal(item.taxable_amount),
                source_payroll_periods=item.source_payroll_periods,
            )
            for item in result_models
        ),
    )


def _cutoff_benefit_entity(model: CutoffBenefitModel) -> CutoffBenefit:
    return CutoffBenefit(
        id=model.id,
        cutoff_id=model.cutoff_id,
        employee_id=model.employee_id,
        benefit_type_id=model.benefit_type_id,
        benefit_code=model.benefit_code,
        benefit_name=model.benefit_name,
        category=model.category,
        tax_treatment=model.tax_treatment,
        amount=Decimal(model.amount),
        notes=model.notes,
        attendance_based=model.attendance_based,
        deduct_for_late=model.deduct_for_late,
        deduct_for_undertime=model.deduct_for_undertime,
    )


def _contribution_bracket_entity(
    model: StatutoryContributionBracketModel,
) -> ContributionBracket:
    return ContributionBracket(
        id=model.id,
        schedule_id=model.schedule_id,
        bracket_number=model.bracket_number,
        compensation_min=Decimal(model.compensation_min),
        compensation_max=(
            Decimal(model.compensation_max) if model.compensation_max is not None else None
        ),
        contribution_base=Decimal(model.contribution_base),
        employee_rate=Decimal(model.employee_rate),
        employer_rate=Decimal(model.employer_rate),
        employee_fixed_amount=Decimal(model.employee_fixed_amount),
        employer_fixed_amount=Decimal(model.employer_fixed_amount),
        employer_additional_fixed_amount=Decimal(model.employer_additional_fixed_amount),
        employee_contribution_cap=(
            Decimal(model.employee_contribution_cap)
            if model.employee_contribution_cap is not None else None
        ),
        employer_contribution_cap=(
            Decimal(model.employer_contribution_cap)
            if model.employer_contribution_cap is not None else None
        ),
    )


def _tax_schedule_entity(model: WithholdingTaxScheduleModel) -> WithholdingTaxSchedule:
    return WithholdingTaxSchedule(
        id=model.id,
        schedule_name=model.schedule_name,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        tax_exempt_benefit_limit=Decimal(model.tax_exempt_benefit_limit),
        calculation_basis=model.calculation_basis,
        source_reference=model.source_reference,
        status=model.status,
        created_at=model.created_at,
        created_by=model.created_by,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
        row_version=model.row_version,
    )


def _tax_bracket_entity(model: WithholdingTaxBracketModel) -> WithholdingTaxBracket:
    return WithholdingTaxBracket(
        id=model.id,
        schedule_id=model.schedule_id,
        bracket_number=model.bracket_number,
        annual_income_min=Decimal(model.annual_income_min),
        annual_income_max=(
            Decimal(model.annual_income_max) if model.annual_income_max is not None else None
        ),
        base_tax=Decimal(model.base_tax),
        marginal_rate=Decimal(model.marginal_rate),
        excess_over=Decimal(model.excess_over),
    )


def _opening_ytd_entity(model: PayrollOpeningYtdBalanceModel) -> OpeningYtdBalance:
    return OpeningYtdBalance(
        id=model.id,
        employee_id=model.employee_id,
        tax_year=model.tax_year,
        taxable_income=Decimal(model.taxable_income),
        tax_withheld=Decimal(model.tax_withheld),
        exempt_limited_benefits=Decimal(model.exempt_limited_benefits),
        created_at=model.created_at,
        created_by=model.created_by,
        previous_balance_id=model.previous_balance_id,
    )


async def _current_opening_ytd_balance(
    session: AsyncSession, employee_id: UUID, tax_year: int
) -> PayrollOpeningYtdBalanceModel | None:
    superseded_ids = select(PayrollOpeningYtdBalanceModel.previous_balance_id).where(
        PayrollOpeningYtdBalanceModel.employee_id == employee_id,
        PayrollOpeningYtdBalanceModel.tax_year == tax_year,
        PayrollOpeningYtdBalanceModel.previous_balance_id.is_not(None),
    )
    return await session.scalar(
        select(PayrollOpeningYtdBalanceModel)
        .where(
            PayrollOpeningYtdBalanceModel.employee_id == employee_id,
            PayrollOpeningYtdBalanceModel.tax_year == tax_year,
            PayrollOpeningYtdBalanceModel.id.not_in(superseded_ids),
        )
        .limit(1)
    )


async def _current_opening_ytd_balances(
    session: AsyncSession, employee_ids: Sequence[UUID], tax_year: int
) -> dict[UUID, PayrollOpeningYtdBalanceModel]:
    superseded_ids = select(PayrollOpeningYtdBalanceModel.previous_balance_id).where(
        PayrollOpeningYtdBalanceModel.employee_id.in_(employee_ids),
        PayrollOpeningYtdBalanceModel.tax_year == tax_year,
        PayrollOpeningYtdBalanceModel.previous_balance_id.is_not(None),
    )
    balances: dict[UUID, PayrollOpeningYtdBalanceModel] = {}
    for model in await session.scalars(
        select(PayrollOpeningYtdBalanceModel).where(
            PayrollOpeningYtdBalanceModel.employee_id.in_(employee_ids),
            PayrollOpeningYtdBalanceModel.tax_year == tax_year,
            PayrollOpeningYtdBalanceModel.id.not_in(superseded_ids),
        )
    ):
        balances.setdefault(model.employee_id, model)
    return balances


class SqlAlchemyPayrollRepository:
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def _validate_compensation_period(
        self,
        session: AsyncSession,
        *,
        employee_id: UUID,
        payroll_group: PayrollGroupModel,
        effective_from: date,
        effective_to: date | None,
        exclude_compensation_id: UUID | None = None,
    ) -> None:
        assignment_conditions = [
            EmploymentAssignmentModel.employee_id == employee_id,
            EmploymentAssignmentModel.company_id == payroll_group.company_id,
            EmploymentAssignmentModel.payroll_group_id == payroll_group.id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            or_(
                EmploymentAssignmentModel.effective_to.is_(None),
                EmploymentAssignmentModel.effective_to >= effective_from,
            ),
            or_(
                EmploymentAssignmentModel.separation_date.is_(None),
                EmploymentAssignmentModel.separation_date >= effective_from,
            ),
        ]
        if effective_to is not None:
            assignment_conditions.append(
                EmploymentAssignmentModel.effective_from <= effective_to
            )
        assignments = list(
            (
                await session.execute(
                    select(
                        EmploymentAssignmentModel.effective_from,
                        EmploymentAssignmentModel.effective_to,
                        EmploymentAssignmentModel.separation_date,
                    )
                    .where(*assignment_conditions)
                    .order_by(EmploymentAssignmentModel.effective_from)
                )
            ).all()
        )
        require_exact_assignment_coverage(effective_from, effective_to, assignments)

        overlap_conditions = [
            EmployeeCompensationModel.employee_id == employee_id,
            EmployeeCompensationModel.payroll_group_id == payroll_group.id,
            EmployeeCompensationModel.is_active.is_(True),
            or_(
                EmployeeCompensationModel.effective_to.is_(None),
                EmployeeCompensationModel.effective_to >= effective_from,
            ),
        ]
        if effective_to is not None:
            overlap_conditions.append(
                EmployeeCompensationModel.effective_from <= effective_to
            )
        if exclude_compensation_id is not None:
            overlap_conditions.append(EmployeeCompensationModel.id != exclude_compensation_id)
        overlap = await session.scalar(
            select(EmployeeCompensationModel.id).where(*overlap_conditions).limit(1)
        )
        if overlap is not None:
            raise ValueError("An active compensation already overlaps these effective dates.")

    async def create_compensation(
        self,
        *,
        employee_id: UUID,
        payroll_group_id: UUID,
        base_rate: str,
        currency: str,
        effective_from: date,
        effective_to: date | None,
        actor_id: UUID,
    ) -> Compensation:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            employee = await session.scalar(
                select(EmployeeModel)
                .where(
                    EmployeeModel.id == employee_id,
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                )
                .with_for_update()
            )
            if employee is None:
                raise ValueError("An active employee is required for compensation.")
            payroll_group = await session.get(PayrollGroupModel, payroll_group_id)
            if payroll_group is None or not payroll_group.is_active or payroll_group.status != "ACTIVE":
                raise ValueError("An active payroll group is required for compensation.")
            await self._validate_compensation_period(
                session,
                employee_id=employee_id,
                payroll_group=payroll_group,
                effective_from=effective_from,
                effective_to=effective_to,
            )
            model = EmployeeCompensationModel(
                employee_id=employee_id,
                payroll_group_id=payroll_group_id,
                base_rate=Decimal(base_rate),
                currency=currency,
                effective_from=effective_from,
                effective_to=effective_to,
                is_active=True,
                created_by=actor_id,
                updated_by=actor_id,
            )
            session.add(model)
            await session.flush()
            return _compensation_entity(model)

    async def update_compensation(
        self,
        *,
        compensation_id: UUID,
        base_rate: str,
        currency: str,
        effective_from: date,
        effective_to: date | None,
        actor_id: UUID,
    ) -> Compensation:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(EmployeeCompensationModel)
                .where(EmployeeCompensationModel.id == compensation_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Employee compensation not found.")

            employee = await session.scalar(
                select(EmployeeModel)
                .where(
                    EmployeeModel.id == model.employee_id,
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                )
                .with_for_update()
            )
            if employee is None:
                raise ValueError("An active employee is required for compensation.")
            payroll_group = await session.get(PayrollGroupModel, model.payroll_group_id)
            if payroll_group is None or not payroll_group.is_active or payroll_group.status != "ACTIVE":
                raise ValueError("An active payroll group is required for compensation.")
            await self._validate_compensation_period(
                session,
                employee_id=model.employee_id,
                payroll_group=payroll_group,
                effective_from=effective_from,
                effective_to=effective_to,
                exclude_compensation_id=model.id,
            )
            model.base_rate = Decimal(base_rate)
            model.currency = currency
            model.effective_from = effective_from
            model.effective_to = effective_to
            model.updated_by = actor_id
            model.row_version += 1
            await session.flush()
            return _compensation_entity(model)

    async def list_compensations(
        self, employee_id: UUID | None, payroll_group_id: UUID | None
    ) -> list[Compensation]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            query = select(EmployeeCompensationModel)
            if employee_id is not None:
                query = query.where(EmployeeCompensationModel.employee_id == employee_id)
            if payroll_group_id is not None:
                query = query.where(EmployeeCompensationModel.payroll_group_id == payroll_group_id)
            models = await session.scalars(
                query.order_by(
                    EmployeeCompensationModel.employee_id,
                    EmployeeCompensationModel.effective_from.desc(),
                )
            )
            return [_compensation_entity(model) for model in models]

    async def save_earning_rule(
        self,
        *,
        payroll_group_id: UUID,
        component_code: str,
        multiplier: str,
        actor_id: UUID,
        rule_id: UUID | None = None,
    ) -> EarningRule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            group = await session.get(PayrollGroupModel, payroll_group_id)
            if group is None:
                raise ValueError("Payroll group not found.")
            model = None
            if rule_id is not None:
                model = await session.scalar(
                    select(PayrollEarningRuleModel)
                    .where(
                        PayrollEarningRuleModel.id == rule_id,
                        PayrollEarningRuleModel.payroll_group_id == payroll_group_id,
                    )
                    .with_for_update()
                )
                if model is None:
                    raise LookupError("Payroll earning rule not found for this payroll group.")
            else:
                model = await session.scalar(
                    select(PayrollEarningRuleModel)
                    .where(
                        PayrollEarningRuleModel.payroll_group_id == payroll_group_id,
                        PayrollEarningRuleModel.component_code == component_code,
                    )
                    .with_for_update()
                )
            if model is None:
                model = PayrollEarningRuleModel(
                    payroll_group_id=payroll_group_id,
                    component_code=component_code,
                    multiplier=Decimal(multiplier),
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                session.add(model)
            else:
                if model.component_code != component_code:
                    raise ValueError("An earning rule's component code cannot be changed.")
                model.multiplier = Decimal(multiplier)
                model.updated_by = actor_id
                model.updated_at = datetime.now(timezone.utc)
                model.row_version += 1
            await session.flush()
            return EarningRule(component_code=model.component_code, multiplier=Decimal(model.multiplier))

    async def list_earning_rules(self, payroll_group_id: UUID) -> list[EarningRule]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = await session.scalars(
                select(PayrollEarningRuleModel)
                .where(PayrollEarningRuleModel.payroll_group_id == payroll_group_id)
                .order_by(PayrollEarningRuleModel.component_code)
            )
            return [
                EarningRule(component_code=model.component_code, multiplier=Decimal(model.multiplier))
                for model in models
            ]

    async def load_cutoff_payroll_data(self, cutoff_id: UUID) -> CutoffPayrollData:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.get(PayrollCutoffModel, cutoff_id)
            if cutoff is None or not cutoff.is_active:
                raise LookupError("Payroll cutoff not found.")
            group = await session.get(PayrollGroupModel, cutoff.payroll_group_id)
            if group is None:
                raise RuntimeError("The payroll cutoff's payroll group could not be loaded.")
            system_parameters = await _company_system_parameters(session, group.company_id)
            result_models = await session.scalars(
                select(EmployeeCutoffResultModel)
                .where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
                .order_by(EmployeeCutoffResultModel.employee_id)
            )
            employees = tuple(
                CutoffEmployeeTime(
                    employee_id=result.employee_id,
                    cutoff_result_id=result.id,
                    component_minutes={
                        "regular_minutes": result.regular_minutes,
                        "paid_leave_minutes": result.paid_leave_minutes,
                        "official_business_minutes": result.official_business_minutes,
                        "rest_day_minutes": result.rest_day_minutes,
                        "special_day_minutes": result.special_day_minutes,
                        "holiday_minutes": result.holiday_minutes,
                        "ordinary_ot_minutes": result.ordinary_ot_minutes,
                        "rest_day_ot_minutes": result.rest_day_ot_minutes,
                        "special_day_ot_minutes": result.special_day_ot_minutes,
                        "holiday_ot_minutes": result.holiday_ot_minutes,
                        "night_regular_minutes": result.night_regular_minutes,
                        "night_ot_minutes": result.night_ot_minutes,
                    },
                    required_work_minutes=result.required_work_minutes,
                    incomplete_time_source_count=result.incomplete_time_source_count,
                )
                for result in result_models
            )
            return CutoffPayrollData(
                cutoff_id=cutoff.id,
                cutoff_code=cutoff.cutoff_code,
                period_start=cutoff.period_start,
                period_end=cutoff.period_end,
                is_locked=cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED",
                is_attendance_finalized=cutoff.attendance_finalized_at is not None,
                payroll_group=PayrollGroupPolicy(
                    payroll_group_id=group.id,
                    rate_type=group.rate_type,
                    pay_frequency=group.pay_frequency,
                    standard_minutes_per_day=group.standard_minutes_per_day,
                    annual_divisor=(
                        Decimal(group.annual_divisor)
                        if group.annual_divisor is not None
                        else None
                    ),
                ),
                employees=employees,
                year_end_wtax_reconciliation_enabled=(
                    system_parameters.year_end_wtax_reconciliation_enabled
                ),
                cutoff_half=cutoff.cutoff_half,
            )

    async def load_covering_compensations(
        self,
        employee_ids: Sequence[UUID],
        payroll_group_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[UUID, Compensation | None]:
        """Return the single covering compensation per employee, or None when ambiguous/missing."""
        employee_ids = list(dict.fromkeys(employee_ids))
        if not employee_ids:
            return {}
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            compensations: dict[UUID, list[EmployeeCompensationModel]] = {
                employee_id: [] for employee_id in employee_ids
            }
            for model in await session.scalars(
                select(EmployeeCompensationModel).where(
                    EmployeeCompensationModel.employee_id.in_(employee_ids),
                    EmployeeCompensationModel.payroll_group_id == payroll_group_id,
                    EmployeeCompensationModel.is_active.is_(True),
                    EmployeeCompensationModel.effective_from <= period_start,
                    or_(
                        EmployeeCompensationModel.effective_to.is_(None),
                        EmployeeCompensationModel.effective_to >= period_end,
                    ),
                )
            ):
                compensations[model.employee_id].append(model)
            assignment_counts: dict[UUID, int] = {
                employee_id: count
                for employee_id, count in (
                    await session.execute(
                        select(
                            EmploymentAssignmentModel.employee_id,
                            func.count(EmploymentAssignmentModel.id),
                        )
                        .join(
                            PayrollGroupModel,
                            PayrollGroupModel.id == EmploymentAssignmentModel.payroll_group_id,
                        )
                        .where(
                            EmploymentAssignmentModel.employee_id.in_(employee_ids),
                            EmploymentAssignmentModel.payroll_group_id == payroll_group_id,
                            EmploymentAssignmentModel.company_id == PayrollGroupModel.company_id,
                            EmploymentAssignmentModel.is_active.is_(True),
                            EmploymentAssignmentModel.effective_from <= period_start,
                            or_(
                                EmploymentAssignmentModel.effective_to.is_(None),
                                EmploymentAssignmentModel.effective_to >= period_end,
                            ),
                            or_(
                                EmploymentAssignmentModel.separation_date.is_(None),
                                EmploymentAssignmentModel.separation_date >= period_end,
                            ),
                        )
                        .group_by(EmploymentAssignmentModel.employee_id)
                    )
                ).all()
            }
            return {
                employee_id: (
                    _compensation_entity(models[0])
                    if len(models) == 1 and assignment_counts.get(employee_id) == 1
                    else None
                )
                for employee_id, models in compensations.items()
            }

    async def save_gross_pay_run(
        self,
        *,
        cutoff_id: UUID,
        actor_id: UUID,
        calculated_at: datetime,
        results: list[GrossPayResult],
    ) -> GrossPayRun:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.scalar(
                select(PayrollCutoffModel)
                .where(PayrollCutoffModel.id == cutoff_id)
                .with_for_update()
            )
            if cutoff is None or not cutoff.is_active:
                raise LookupError("Payroll cutoff not found.")
            if cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED":
                raise ValueError("A locked payroll cutoff cannot be recalculated.")
            if cutoff.attendance_finalized_at is None:
                raise ValueError(
                    "Finalize attendance for this cutoff before calculating payroll."
                )
            current_run = await session.scalars(
                select(GrossPayRunModel)
                .where(
                    GrossPayRunModel.cutoff_id == cutoff_id,
                    GrossPayRunModel.is_current.is_(True),
                )
                .with_for_update()
            )
            for run in current_run:
                run.is_current = False
            run = GrossPayRunModel(
                cutoff_id=cutoff_id,
                calculation_version="GROSS_PAY_V1",
                calculated_at=calculated_at,
                calculated_by=actor_id,
                is_current=True,
            )
            session.add(run)
            await session.flush()
            previous_repayments = list(
                (
                    await session.scalars(
                        select(EmployeeLoanRepaymentModel)
                        .where(EmployeeLoanRepaymentModel.cutoff_id == cutoff_id)
                        .with_for_update()
                    )
                ).all()
            )
            previous_amounts = {
                item.loan_id: Decimal(item.amount) for item in previous_repayments
            }
            for repayment in previous_repayments:
                await session.delete(repayment)
            new_amounts: dict[UUID, Decimal] = {}
            for result in results:
                if result.status != "READY":
                    continue
                for line in result.benefit_lines:
                    if line.loan_id is not None:
                        new_amounts[line.loan_id] = (
                            new_amounts.get(line.loan_id, Decimal(0)) + line.amount
                        )
            for loan_id in sorted(set(previous_amounts) | set(new_amounts), key=str):
                loan = await session.scalar(
                    select(EmployeeLoanModel)
                    .where(EmployeeLoanModel.id == loan_id)
                    .with_for_update()
                )
                if loan is None:
                    raise RuntimeError("A loan referenced by the payroll run could not be loaded.")
                restored_balance = Decimal(loan.outstanding_balance) + previous_amounts.get(
                    loan_id, Decimal(0)
                )
                new_amount = new_amounts.get(loan_id, Decimal(0))
                if new_amount > restored_balance:
                    raise ValueError(
                        f"Loan {loan.reference_number} has insufficient balance for this payroll installment. Recalculate payroll."
                    )
                loan.outstanding_balance = restored_balance - new_amount
                if loan.status != "RETIRED":
                    loan.status = "PAID_OFF" if loan.outstanding_balance == 0 else "ACTIVE"
                if new_amount > 0:
                    session.add(
                        EmployeeLoanRepaymentModel(
                            loan_id=loan_id,
                            cutoff_id=cutoff_id,
                            gross_pay_run_id=run.id,
                            amount=new_amount,
                        )
                    )
            result_models = [
                GrossPayResultModel(
                    run_id=run.id,
                    employee_id=result.employee_id,
                    cutoff_result_id=result.cutoff_result_id,
                    currency=result.currency,
                    base_rate=result.base_rate,
                    gross_amount=result.gross_amount,
                    status=result.status,
                    gross_status=result.gross_status or result.status,
                    hold_reason=result.hold_reason,
                    cash_benefit_amount=result.cash_benefit_amount,
                    non_cash_benefit_amount=result.non_cash_benefit_amount,
                    employee_benefit_deductions=result.employee_benefit_deductions,
                    exempt_limited_benefit_amount=result.exempt_limited_benefit_amount,
                    taxable_income=result.taxable_income,
                    employee_contributions=result.employee_contributions,
                    employer_contributions=result.employer_contributions,
                    withholding_tax=result.withholding_tax,
                    net_amount=result.net_amount,
                    earning_lines=[
                        {
                            "component_code": line.component_code,
                            "minutes": line.minutes,
                            "multiplier": str(line.multiplier),
                            "amount": str(line.amount),
                        }
                        for line in result.lines
                    ],
                    benefit_lines=[
                        {
                            "benefit_code": line.benefit_code,
                            "benefit_name": line.benefit_name,
                            "category": line.category,
                            "tax_treatment": line.tax_treatment,
                            "withholding_timing": line.withholding_timing,
                            "amount": str(line.amount),
                            "loan_id": str(line.loan_id) if line.loan_id else None,
                        }
                        for line in result.benefit_lines
                    ],
                    contribution_lines=[
                        {
                            "program_code": line.program_code,
                            "employee_amount": str(line.employee_amount),
                            "employer_amount": str(line.employer_amount),
                        }
                        for line in result.contribution_lines
                    ],
                    source_minutes=result.source_minutes,
                )
                for result in results
            ]
            session.add_all(result_models)
            await session.flush()
            return _run_entity(run, result_models)

    async def calculate_thirteenth_month_run(
        self,
        *,
        company_id: UUID,
        tax_year: int,
        covered_period_from: date,
        covered_period_to: date,
        actor_id: UUID,
        calculated_at: datetime,
    ) -> ThirteenthMonthRun:
        year_start = date(tax_year, 1, 1)
        year_end = date(tax_year, 12, 31)
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            parameters = await _company_system_parameters(session, company_id)
            if not parameters.thirteenth_month_enabled:
                raise ValueError("Enable 13th-month pay calculation in payroll system parameters first.")

            cutoff_exists = await session.scalar(
                select(PayrollCutoffModel.id)
                .join(
                    PayrollGroupModel,
                    PayrollGroupModel.id == PayrollCutoffModel.payroll_group_id,
                )
                .where(
                    PayrollGroupModel.company_id == company_id,
                    PayrollCutoffModel.period_start == covered_period_from,
                    PayrollCutoffModel.period_end == covered_period_to,
                    PayrollCutoffModel.is_active.is_(True),
                )
                .limit(1)
            )
            if cutoff_exists is None:
                raise ValueError(
                    "The entered From and To dates do not match an active payroll cutoff for this company."
                )

            tax_schedules = list(
                (
                    await session.scalars(
                        select(WithholdingTaxScheduleModel).where(
                            WithholdingTaxScheduleModel.status == "ACTIVE",
                            WithholdingTaxScheduleModel.effective_from <= year_end,
                            or_(
                                WithholdingTaxScheduleModel.effective_to.is_(None),
                                WithholdingTaxScheduleModel.effective_to >= year_end,
                            ),
                        )
                    )
                ).all()
            )
            if len(tax_schedules) != 1:
                raise ValueError(
                    "Exactly one active withholding-tax schedule must cover December 31 to apply the shared benefit exemption."
                )
            benefit_exemption_limit = Decimal(tax_schedules[0].tax_exempt_benefit_limit)

            prior_exempt_rows = await session.execute(
                select(
                    GrossPayResultModel.employee_id,
                    func.sum(GrossPayResultModel.exempt_limited_benefit_amount),
                )
                .join(GrossPayRunModel, GrossPayRunModel.id == GrossPayResultModel.run_id)
                .join(PayrollCutoffModel, PayrollCutoffModel.id == GrossPayRunModel.cutoff_id)
                .join(PayrollGroupModel, PayrollGroupModel.id == PayrollCutoffModel.payroll_group_id)
                .where(
                    GrossPayRunModel.is_current.is_(True),
                    GrossPayResultModel.status == "READY",
                    PayrollCutoffModel.period_end >= year_start,
                    PayrollCutoffModel.period_end <= covered_period_to,
                    PayrollGroupModel.company_id == company_id,
                )
                .group_by(GrossPayResultModel.employee_id)
            )
            prior_exempt_by_employee = {
                employee_id: Decimal(amount or 0)
                for employee_id, amount in prior_exempt_rows
            }
            off_cycle_exempt_rows = await session.execute(
                select(
                    OffCyclePayrollLineModel.employee_id,
                    func.sum(OffCyclePayrollLineModel.exempt_limited_amount),
                )
                .join(
                    OffCyclePayrollRunModel,
                    OffCyclePayrollRunModel.id == OffCyclePayrollLineModel.run_id,
                )
                .where(
                    OffCyclePayrollRunModel.company_id == company_id,
                    OffCyclePayrollRunModel.status == "PAID",
                    OffCyclePayrollRunModel.actual_payment_date >= year_start,
                    OffCyclePayrollRunModel.actual_payment_date <= covered_period_to,
                    OffCyclePayrollLineModel.thirteenth_month_result_id.is_(None),
                )
                .group_by(OffCyclePayrollLineModel.employee_id)
            )
            for employee_id, amount in off_cycle_exempt_rows:
                prior_exempt_by_employee[employee_id] = (
                    prior_exempt_by_employee.get(employee_id, Decimal(0))
                    + Decimal(amount or 0)
                )

            earning_rows = await session.execute(
                select(
                    PayrollCutoffModel.id,
                    GrossPayResultModel.employee_id,
                    GrossPayResultModel.earning_lines,
                    EmployeeModel.employee_no,
                    EmployeeModel.first_name,
                    EmployeeModel.middle_name,
                    EmployeeModel.last_name,
                    EmployeeModel.suffix,
                )
                .join(GrossPayRunModel, GrossPayRunModel.cutoff_id == PayrollCutoffModel.id)
                .join(GrossPayResultModel, GrossPayResultModel.run_id == GrossPayRunModel.id)
                .join(EmployeeModel, EmployeeModel.id == GrossPayResultModel.employee_id)
                .join(PayrollGroupModel, PayrollGroupModel.id == PayrollCutoffModel.payroll_group_id)
                .where(
                    GrossPayRunModel.is_current.is_(True),
                    GrossPayResultModel.status == "READY",
                    PayrollCutoffModel.period_end >= year_start,
                    PayrollCutoffModel.period_end <= covered_period_to,
                    PayrollGroupModel.company_id == company_id,
                )
            )
            basic_salary_by_employee: dict[UUID, Decimal] = {}
            source_periods_by_employee: dict[UUID, set[UUID]] = {}
            employee_names: dict[UUID, tuple[str, str]] = {}
            for (
                cutoff_id,
                employee_id,
                earning_lines,
                employee_no,
                first_name,
                middle_name,
                last_name,
                suffix,
            ) in earning_rows:
                period_basic_salary = sum(
                    (
                        Decimal(str(line["amount"]))
                        for line in earning_lines
                        if line["component_code"]
                        in {
                            "REGULAR",
                            "PAID_LEAVE",
                            "MONTHLY_BASE",
                            "UNPAID_TIME_DEDUCTION",
                        }
                    ),
                    Decimal(0),
                )
                if period_basic_salary != 0:
                    basic_salary_by_employee[employee_id] = (
                        basic_salary_by_employee.get(employee_id, Decimal(0))
                        + period_basic_salary
                    )
                    source_periods_by_employee.setdefault(employee_id, set()).add(cutoff_id)
                employee_names[employee_id] = (
                    employee_no,
                    " ".join(
                        part
                        for part in (
                            first_name,
                            middle_name,
                            last_name,
                            suffix,
                        )
                        if part
                    ),
                )

            basic_salary_by_employee = {
                employee_id: amount
                for employee_id, amount in basic_salary_by_employee.items()
                if amount > 0
            }
            if not basic_salary_by_employee:
                raise ValueError(
                    f"No completed payroll results with basic salary were found for {tax_year}."
                )
            for employee_id in basic_salary_by_employee:
                opening_balance = await _current_opening_ytd_balance(
                    session, employee_id, tax_year
                )
                if opening_balance is not None:
                    prior_exempt_by_employee[employee_id] = (
                        prior_exempt_by_employee.get(employee_id, Decimal(0))
                        + Decimal(opening_balance.exempt_limited_benefits)
                    )

            current_runs = await session.scalars(
                select(ThirteenthMonthRunModel)
                .where(
                    ThirteenthMonthRunModel.tax_year == tax_year,
                    ThirteenthMonthRunModel.company_id == company_id,
                    ThirteenthMonthRunModel.is_current.is_(True),
                )
                .with_for_update()
            )
            for current_run in current_runs:
                current_run.is_current = False
            run = ThirteenthMonthRunModel(
                company_id=company_id,
                tax_year=tax_year,
                covered_period_from=covered_period_from,
                covered_period_to=covered_period_to,
                calculated_at=calculated_at,
                calculated_by=actor_id,
                is_current=True,
            )
            session.add(run)
            await session.flush()

            result_models: list[ThirteenthMonthResultModel] = []
            for employee_id, basic_salary in sorted(
                basic_salary_by_employee.items(), key=lambda item: str(item[0])
            ):
                amounts = calculate_thirteenth_month_amounts(
                    basic_salary_earned=basic_salary,
                    annual_benefit_exemption_limit=benefit_exemption_limit,
                    prior_ytd_exempt_benefits=prior_exempt_by_employee.get(
                        employee_id, Decimal(0)
                    ),
                )
                result_models.append(
                    ThirteenthMonthResultModel(
                        run_id=run.id,
                        employee_id=employee_id,
                        employee_no=employee_names[employee_id][0],
                        employee_name=employee_names[employee_id][1],
                        basic_salary_earned=amounts.basic_salary_earned,
                        thirteenth_month_pay=amounts.thirteenth_month_pay,
                        tax_exempt_amount=amounts.tax_exempt_amount,
                        taxable_amount=amounts.taxable_amount,
                        source_payroll_periods=len(source_periods_by_employee[employee_id]),
                    )
                )
            session.add_all(result_models)
            await session.flush()
            return _thirteenth_month_run_entity(run, result_models)

    async def load_net_payroll_inputs(
        self, cutoff_id: UUID, employee_ids: Sequence[UUID]
    ) -> dict[UUID, NetPayrollInputs]:
        """Load net-pay inputs for many employees with a fixed number of queries."""
        employee_ids = list(dict.fromkeys(employee_ids))
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.get(PayrollCutoffModel, cutoff_id)
            if cutoff is None or not cutoff.is_active:
                raise LookupError("Payroll cutoff not found.")
            group = await session.get(PayrollGroupModel, cutoff.payroll_group_id)
            if group is None:
                raise RuntimeError("The payroll cutoff's payroll group could not be loaded.")
            if not employee_ids:
                return {}
            system_parameters = await _company_system_parameters(session, group.company_id)

            contribution_brackets: dict[
                ContributionProgram, tuple[ContributionBracket, ...]
            ] = {}
            for program in REQUIRED_CONTRIBUTION_PROGRAMS:
                schedules = list(
                    (
                        await session.scalars(
                            select(StatutoryContributionScheduleModel).where(
                                StatutoryContributionScheduleModel.program_code == program,
                                StatutoryContributionScheduleModel.status == "ACTIVE",
                                StatutoryContributionScheduleModel.effective_from
                                <= cutoff.period_end,
                                or_(
                                    StatutoryContributionScheduleModel.effective_to.is_(None),
                                    StatutoryContributionScheduleModel.effective_to
                                    >= cutoff.period_end,
                                ),
                            )
                        )
                    ).all()
                )
                if len(schedules) != 1:
                    contribution_brackets[program] = ()
                    continue
                bracket_models = await session.scalars(
                    select(StatutoryContributionBracketModel)
                    .where(StatutoryContributionBracketModel.schedule_id == schedules[0].id)
                    .order_by(StatutoryContributionBracketModel.bracket_number)
                )
                contribution_brackets[program] = tuple(
                    _contribution_bracket_entity(item) for item in bracket_models
                )

            tax_schedules = list(
                (
                    await session.scalars(
                        select(WithholdingTaxScheduleModel).where(
                            WithholdingTaxScheduleModel.status == "ACTIVE",
                            WithholdingTaxScheduleModel.effective_from <= cutoff.period_end,
                            or_(
                                WithholdingTaxScheduleModel.effective_to.is_(None),
                                WithholdingTaxScheduleModel.effective_to >= cutoff.period_end,
                            ),
                        )
                    )
                ).all()
            )
            tax_schedule = _tax_schedule_entity(tax_schedules[0]) if len(tax_schedules) == 1 else None
            tax_brackets: tuple[WithholdingTaxBracket, ...] = ()
            if tax_schedule is not None:
                bracket_models = await session.scalars(
                    select(WithholdingTaxBracketModel)
                    .where(WithholdingTaxBracketModel.schedule_id == tax_schedule.id)
                    .order_by(WithholdingTaxBracketModel.bracket_number)
                )
                tax_brackets = tuple(_tax_bracket_entity(item) for item in bracket_models)

            month_start = date(cutoff.period_end.year, cutoff.period_end.month, 1)
            month_end = date(
                cutoff.period_end.year,
                cutoff.period_end.month,
                monthrange(cutoff.period_end.year, cutoff.period_end.month)[1],
            )
            monthly_cutoffs = list(
                (
                    await session.scalars(
                        select(PayrollCutoffModel)
                        .where(
                            PayrollCutoffModel.payroll_group_id == cutoff.payroll_group_id,
                            PayrollCutoffModel.is_active.is_(True),
                            PayrollCutoffModel.period_end >= month_start,
                            PayrollCutoffModel.period_end <= month_end,
                        )
                        .order_by(
                            PayrollCutoffModel.period_start,
                            PayrollCutoffModel.period_end,
                            PayrollCutoffModel.cutoff_code,
                        )
                    )
                ).all()
            )
            cutoff_ids = [item.id for item in monthly_cutoffs]
            cutoff_number = cutoff_ids.index(cutoff_id) + 1 if cutoff_id in cutoff_ids else 0
            tax_year_start = date(cutoff.period_end.year, 1, 1)
            is_final_december_cutoff = (
                cutoff.period_end.month == 12
                and cutoff_number == len(monthly_cutoffs)
            )

            manual_benefits: dict[UUID, list[CutoffBenefit]] = {
                employee_id: [] for employee_id in employee_ids
            }
            for item in await session.scalars(
                select(CutoffBenefitModel)
                .where(
                    CutoffBenefitModel.cutoff_id == cutoff_id,
                    CutoffBenefitModel.employee_id.in_(employee_ids),
                )
                .order_by(CutoffBenefitModel.id)
            ):
                manual_benefits[item.employee_id].append(_cutoff_benefit_entity(item))

            deductions_by_employee: dict[
                UUID, list[tuple[EmployeeBenefitDeductionModel, BenefitTypeModel]]
            ] = {employee_id: [] for employee_id in employee_ids}
            for deduction, benefit_type in (
                await session.execute(
                    select(EmployeeBenefitDeductionModel, BenefitTypeModel)
                    .join(
                        BenefitTypeModel,
                        BenefitTypeModel.id == EmployeeBenefitDeductionModel.benefit_type_id,
                    )
                    .where(
                        EmployeeBenefitDeductionModel.employee_id.in_(employee_ids),
                        EmployeeBenefitDeductionModel.is_active.is_(True),
                        EmployeeBenefitDeductionModel.effective_from <= cutoff.period_start,
                        or_(
                            EmployeeBenefitDeductionModel.effective_to.is_(None),
                            EmployeeBenefitDeductionModel.effective_to >= cutoff.period_end,
                        ),
                        BenefitTypeModel.payroll_group_id == cutoff.payroll_group_id,
                        BenefitTypeModel.category == "EMPLOYEE_DEDUCTION",
                        BenefitTypeModel.is_active.is_(True),
                    )
                )
            ).all():
                deductions_by_employee[deduction.employee_id].append((deduction, benefit_type))

            loans_by_employee: dict[UUID, list[EmployeeLoanModel]] = {
                employee_id: [] for employee_id in employee_ids
            }
            for loan in (
                await session.scalars(
                    select(EmployeeLoanModel).where(
                        EmployeeLoanModel.employee_id.in_(employee_ids),
                        EmployeeLoanModel.payroll_group_id == cutoff.payroll_group_id,
                        EmployeeLoanModel.status.in_(("ACTIVE", "PAID_OFF")),
                        EmployeeLoanModel.effective_from <= cutoff.period_start,
                    )
                )
            ).all():
                loans_by_employee[loan.employee_id].append(loan)
            due_loan_ids = [
                loan.id
                for loans in loans_by_employee.values()
                for loan in loans
                if loan_due_this_cutoff(loan.schedule, cutoff.cutoff_half)
            ]
            repayments_by_loan: dict[UUID, EmployeeLoanRepaymentModel] = {}
            if due_loan_ids:
                for repayment in await session.scalars(
                    select(EmployeeLoanRepaymentModel).where(
                        EmployeeLoanRepaymentModel.loan_id.in_(due_loan_ids),
                        EmployeeLoanRepaymentModel.cutoff_id == cutoff_id,
                    )
                ):
                    repayments_by_loan.setdefault(repayment.loan_id, repayment)

            entitlements_by_employee: dict[
                UUID, list[tuple[EmployeeBenefitEntitlementModel, BenefitTypeModel]]
            ] = {employee_id: [] for employee_id in employee_ids}
            for entitlement, benefit_type in (
                await session.execute(
                    select(EmployeeBenefitEntitlementModel, BenefitTypeModel)
                    .join(
                        BenefitTypeModel,
                        BenefitTypeModel.id == EmployeeBenefitEntitlementModel.benefit_type_id,
                    )
                    .where(
                        EmployeeBenefitEntitlementModel.employee_id.in_(employee_ids),
                        EmployeeBenefitEntitlementModel.is_active.is_(True),
                        EmployeeBenefitEntitlementModel.effective_from <= cutoff.period_start,
                        or_(
                            EmployeeBenefitEntitlementModel.effective_to.is_(None),
                            EmployeeBenefitEntitlementModel.effective_to >= cutoff.period_end,
                        ),
                        BenefitTypeModel.payroll_group_id == cutoff.payroll_group_id,
                        BenefitTypeModel.category != "EMPLOYEE_DEDUCTION",
                        BenefitTypeModel.is_active.is_(True),
                    )
                )
            ).all():
                entitlements_by_employee[entitlement.employee_id].append(
                    (entitlement, benefit_type)
                )

            attendance_by_employee: dict[UUID, EmployeeCutoffResultModel] = {}
            for attendance in await session.scalars(
                select(EmployeeCutoffResultModel).where(
                    EmployeeCutoffResultModel.cutoff_id == cutoff_id,
                    EmployeeCutoffResultModel.employee_id.in_(employee_ids),
                )
            ):
                attendance_by_employee.setdefault(attendance.employee_id, attendance)
            if any(employee_id not in attendance_by_employee for employee_id in employee_ids):
                raise RuntimeError("Employee cutoff attendance facts could not be loaded.")

            previous_month_employee, previous_month_employer = (
                await _prior_first_half_contributions(session, cutoff, employee_ids)
            )

            opening_by_employee = await _current_opening_ytd_balances(
                session,
                employee_ids,
                cutoff.period_end.year,
            )
            ytd_rows_by_employee: dict[UUID, list[tuple[Decimal, Decimal, Decimal]]] = {
                employee_id: [] for employee_id in employee_ids
            }
            for employee_id, taxable, tax, limited_benefits in (await session.execute(
                select(
                    GrossPayResultModel.employee_id,
                    GrossPayResultModel.taxable_income,
                    GrossPayResultModel.withholding_tax,
                    GrossPayResultModel.exempt_limited_benefit_amount,
                )
                .join(GrossPayRunModel, GrossPayRunModel.id == GrossPayResultModel.run_id)
                .join(PayrollCutoffModel, PayrollCutoffModel.id == GrossPayRunModel.cutoff_id)
                .where(
                    GrossPayRunModel.is_current.is_(True),
                    PayrollCutoffModel.payroll_group_id == cutoff.payroll_group_id,
                    PayrollCutoffModel.period_end >= tax_year_start,
                    PayrollCutoffModel.period_end < cutoff.period_start,
                    GrossPayResultModel.employee_id.in_(employee_ids),
                    GrossPayResultModel.status == "READY",
                )
            )).all():
                ytd_rows_by_employee[employee_id].append((taxable, tax, limited_benefits))

            off_cycle_effective_date = func.coalesce(
                OffCyclePayrollRunModel.actual_payment_date,
                OffCyclePayrollRunModel.proposed_payment_date,
            )
            for employee_id, taxable, tax, limited_benefits in (await session.execute(
                select(
                    OffCyclePayrollLineModel.employee_id,
                    OffCyclePayrollLineModel.taxable_amount,
                    OffCyclePayrollLineModel.withholding_tax,
                    OffCyclePayrollLineModel.exempt_limited_amount,
                )
                .join(
                    OffCyclePayrollRunModel,
                    OffCyclePayrollRunModel.id == OffCyclePayrollLineModel.run_id,
                )
                .where(
                    OffCyclePayrollRunModel.company_id == group.company_id,
                    OffCyclePayrollRunModel.status == "PAID",
                    off_cycle_effective_date >= tax_year_start,
                    off_cycle_effective_date <= cutoff.period_end,
                    OffCyclePayrollLineModel.employee_id.in_(employee_ids),
                )
            )).all():
                ytd_rows_by_employee[employee_id].append((taxable, tax, limited_benefits))

            thirteenth_month_by_employee: dict[UUID, ThirteenthMonthResultModel] = {}
            if is_final_december_cutoff:
                # 13th-month pay issued through an off-cycle run is counted from its
                # off-cycle line instead, so it is never taxed twice.
                off_cycle_thirteenth_month_ids = (
                    select(OffCyclePayrollLineModel.thirteenth_month_result_id)
                    .join(
                        OffCyclePayrollRunModel,
                        OffCyclePayrollRunModel.id == OffCyclePayrollLineModel.run_id,
                    )
                    .where(
                        OffCyclePayrollLineModel.thirteenth_month_result_id.is_not(None),
                        OffCyclePayrollRunModel.status != "REJECTED",
                    )
                )
                for thirteenth_month_result in await session.scalars(
                    select(ThirteenthMonthResultModel)
                    .join(
                        ThirteenthMonthRunModel,
                        ThirteenthMonthRunModel.id == ThirteenthMonthResultModel.run_id,
                    )
                    .where(
                        ThirteenthMonthRunModel.tax_year == cutoff.period_end.year,
                        ThirteenthMonthRunModel.company_id == group.company_id,
                        ThirteenthMonthRunModel.is_current.is_(True),
                        ThirteenthMonthResultModel.employee_id.in_(employee_ids),
                        ThirteenthMonthResultModel.id.not_in(off_cycle_thirteenth_month_ids),
                    )
                ):
                    thirteenth_month_by_employee.setdefault(
                        thirteenth_month_result.employee_id, thirteenth_month_result
                    )

            inputs: dict[UUID, NetPayrollInputs] = {}
            for employee_id in employee_ids:
                benefits = tuple(manual_benefits[employee_id])
                manual_benefit_types = {
                    item.benefit_type_id
                    for item in benefits
                    if item.category != "EMPLOYEE_DEDUCTION"
                }
                for deduction, benefit_type in deductions_by_employee[employee_id]:
                    if benefit_type.id in manual_benefit_types:
                        continue
                    if not is_employee_deduction_due(deduction.schedule, cutoff.cutoff_half):
                        continue
                    benefits += (
                        CutoffBenefit(
                            id=deduction.id,
                            cutoff_id=cutoff_id,
                            employee_id=employee_id,
                            benefit_type_id=benefit_type.id,
                            benefit_code=benefit_type.code,
                            benefit_name=benefit_type.name,
                            category=benefit_type.category,
                            tax_treatment=benefit_type.tax_treatment,
                            withholding_timing=benefit_type.withholding_timing,
                            amount=Decimal(deduction.amount_per_occurrence),
                            notes=f"Recurring deduction ({deduction.schedule.lower().replace('_', ' ')})",
                        ),
                    )
                for loan in loans_by_employee[employee_id]:
                    if not loan_due_this_cutoff(loan.schedule, cutoff.cutoff_half):
                        continue
                    existing_repayment = repayments_by_loan.get(loan.id)
                    available_balance = Decimal(loan.outstanding_balance)
                    if existing_repayment is not None:
                        available_balance += Decimal(existing_repayment.amount)
                    installment = loan_installment_due(
                        Decimal(loan.installment_amount),
                        available_balance,
                    )
                    if installment <= 0:
                        continue
                    benefits += (
                        CutoffBenefit(
                            id=loan.id,
                            cutoff_id=cutoff_id,
                            employee_id=employee_id,
                            benefit_type_id=loan.id,
                            benefit_code=f"LOAN-{loan.reference_number}",
                            benefit_name=f"Loan repayment - {loan.reference_number}",
                            category="EMPLOYEE_DEDUCTION",
                            tax_treatment="EXEMPT",
                            amount=installment,
                            notes="Employee loan repayment",
                            loan_id=loan.id,
                        ),
                    )
                for entitlement, benefit_type in entitlements_by_employee[employee_id]:
                    if benefit_type.id in manual_benefit_types:
                        continue
                    if not is_benefit_due(entitlement.schedule, cutoff.cutoff_half):
                        continue
                    benefits += (
                        CutoffBenefit(
                            id=entitlement.id,
                            cutoff_id=cutoff_id,
                            employee_id=employee_id,
                            benefit_type_id=benefit_type.id,
                            benefit_code=benefit_type.code,
                            benefit_name=benefit_type.name,
                            category=benefit_type.category,
                            tax_treatment=benefit_type.tax_treatment,
                            withholding_timing=benefit_type.withholding_timing,
                            amount=Decimal(entitlement.amount_per_occurrence),
                            notes=(
                                f"Recurring benefit ({entitlement.schedule.lower().replace('_', ' ')})"
                            ),
                            attendance_based=benefit_type.attendance_based,
                            deduct_for_late=benefit_type.deduct_for_late,
                            deduct_for_undertime=benefit_type.deduct_for_undertime,
                        ),
                    )

                opening_model = opening_by_employee.get(employee_id)
                prior_taxable = (
                    Decimal(opening_model.taxable_income)
                    if opening_model is not None else Decimal(0)
                )
                prior_tax = (
                    Decimal(opening_model.tax_withheld)
                    if opening_model is not None else Decimal(0)
                )
                prior_limited_benefits = (
                    Decimal(opening_model.exempt_limited_benefits)
                    if opening_model is not None else Decimal(0)
                )
                ytd_rows = ytd_rows_by_employee[employee_id]
                for taxable, tax, limited_benefits in ytd_rows:
                    prior_taxable += Decimal(taxable or 0)
                    prior_tax += Decimal(tax or 0)
                    prior_limited_benefits += Decimal(limited_benefits or 0)
                thirteenth_month_result = thirteenth_month_by_employee.get(employee_id)
                if thirteenth_month_result is not None:
                    prior_taxable += Decimal(thirteenth_month_result.taxable_amount)
                    prior_limited_benefits += Decimal(
                        thirteenth_month_result.tax_exempt_amount
                    )

                attendance = attendance_by_employee[employee_id]
                inputs[employee_id] = NetPayrollInputs(
                    benefits=benefits,
                    contribution_brackets=contribution_brackets,
                    tax_schedule=tax_schedule,
                    tax_brackets=tax_brackets,
                    monthly_cutoff_count=len(monthly_cutoffs),
                    cutoff_number_in_month=cutoff_number,
                    prior_month_employee_contributions=previous_month_employee[employee_id],
                    prior_month_employer_contributions=previous_month_employer[employee_id],
                    statutory_contribution_timing=system_parameters.statutory_contribution_timing,
                    pay_frequency=group.pay_frequency,
                    cutoff_half=cutoff.cutoff_half,
                    prior_ytd_taxable_income=prior_taxable,
                    prior_ytd_withholding_tax=prior_tax,
                    prior_ytd_limited_exempt_benefits=prior_limited_benefits,
                    is_final_december_cutoff=is_final_december_cutoff,
                    opening_ytd_balance_missing=(
                        opening_model is None
                        and not ytd_rows
                        and cutoff.period_start > tax_year_start
                    ),
                    scheduled_days=Decimal(attendance.scheduled_days),
                    paid_days=Decimal(attendance.paid_days),
                    required_work_minutes=attendance.required_work_minutes,
                    late_minutes=attendance.late_minutes,
                    undertime_minutes=attendance.undertime_minutes,
                )
            return inputs

    async def get_opening_ytd_balance(
        self, employee_id: UUID, tax_year: int
    ) -> OpeningYtdBalance | None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await _current_opening_ytd_balance(session, employee_id, tax_year)
            return _opening_ytd_entity(model) if model is not None else None

    async def record_opening_ytd_balance(
        self,
        *,
        employee_id: UUID,
        tax_year: int,
        taxable_income: str,
        tax_withheld: str,
        exempt_limited_benefits: str,
        actor_id: UUID,
    ) -> OpeningYtdBalance:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            employee = await session.scalar(
                select(EmployeeModel.id).where(EmployeeModel.id == employee_id).with_for_update()
            )
            if employee is None:
                raise LookupError("Employee not found.")
            previous = await _current_opening_ytd_balance(session, employee_id, tax_year)
            model = PayrollOpeningYtdBalanceModel(
                employee_id=employee_id,
                tax_year=tax_year,
                taxable_income=taxable_income,
                tax_withheld=tax_withheld,
                exempt_limited_benefits=exempt_limited_benefits,
                previous_balance_id=previous.id if previous is not None else None,
                created_by=actor_id,
            )
            session.add(model)
            await session.flush()
            return _opening_ytd_entity(model)

    async def list_my_gross_pay_results(self, user_id: UUID) -> list[GrossPayRun]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            employee_id = await session.scalar(
                select(UserModel.employee_id).where(
                    UserModel.id == user_id,
                    UserModel.is_active.is_(True),
                )
            )
            if employee_id is None:
                return []
            runs = list(
                (
                    await session.scalars(
                        select(GrossPayRunModel)
                        .join(
                            GrossPayResultModel,
                            GrossPayResultModel.run_id == GrossPayRunModel.id,
                        )
                        .where(
                            GrossPayRunModel.is_current.is_(True),
                            GrossPayResultModel.employee_id == employee_id,
                        )
                        .order_by(GrossPayRunModel.calculated_at.desc())
                    )
                ).all()
            )
            results_by_run: dict[UUID, list[GrossPayResultModel]] = {}
            for run in runs:
                result_models = await session.scalars(
                    select(GrossPayResultModel).where(
                        GrossPayResultModel.run_id == run.id,
                        GrossPayResultModel.employee_id == employee_id,
                    )
                )
                results_by_run[run.id] = list(result_models.all())
            return [_run_entity(run, results_by_run[run.id]) for run in runs]

    async def get_current_gross_pay_run(self, cutoff_id: UUID) -> GrossPayRun | None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            run = await session.scalar(
                select(GrossPayRunModel).where(
                    GrossPayRunModel.cutoff_id == cutoff_id,
                    GrossPayRunModel.is_current.is_(True),
                )
            )
            if run is None:
                return None
            result_models = await session.scalars(
                select(GrossPayResultModel)
                .where(GrossPayResultModel.run_id == run.id)
                .order_by(GrossPayResultModel.employee_id)
            )
            return _run_entity(run, list(result_models.all()))

    async def approve_payroll_cutoff(
        self,
        cutoff_id: UUID,
        actor_id: UUID,
        approved_at: datetime,
    ) -> PayrollCutoffLockState:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.scalar(
                select(PayrollCutoffModel)
                .where(
                    PayrollCutoffModel.id == cutoff_id,
                    PayrollCutoffModel.is_active.is_(True),
                )
                .with_for_update()
            )
            if cutoff is None:
                raise LookupError("Payroll cutoff not found.")
            if cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED":
                raise ValueError("This payroll cutoff is already finalized.")
            if cutoff.attendance_deadline is None:
                raise ValueError("Set the cutoff's attendance deadline before approving payroll.")
            if approved_at <= cutoff.attendance_deadline:
                raise ValueError(
                    "Payroll can be approved only after the cutoff's attendance deadline has passed."
                )
            if cutoff.attendance_finalized_at is None:
                raise ValueError(
                    "Finalize attendance for this cutoff before approving payroll."
                )

            run = await session.scalar(
                select(GrossPayRunModel)
                .where(
                    GrossPayRunModel.cutoff_id == cutoff_id,
                    GrossPayRunModel.is_current.is_(True),
                )
                .with_for_update()
            )
            if run is None:
                raise ValueError("Calculate payroll before approving this cutoff.")
            if run.calculated_by == actor_id:
                raise PayrollApprovalPermissionError(
                    "The person who calculated this payroll cannot approve it. "
                    "Another HR administrator must approve it."
                )

            payroll_results = list(
                (
                    await session.scalars(
                        select(GrossPayResultModel)
                        .where(GrossPayResultModel.run_id == run.id)
                        .with_for_update()
                    )
                ).all()
            )
            if not payroll_results:
                raise ValueError("A cutoff with no employee payroll results cannot be approved.")
            if any(result.status != "READY" for result in payroll_results):
                raise ValueError("All employee payroll results must be READY before approval.")

            time_results = list(
                (
                    await session.scalars(
                        select(EmployeeCutoffResultModel)
                        .where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
                        .with_for_update()
                    )
                ).all()
            )
            time_results_by_employee = {
                result.employee_id: result for result in time_results
            }
            if len(time_results_by_employee) != len(payroll_results):
                raise ValueError("Payroll results are out of date. Recalculate payroll before approval.")
            for result in payroll_results:
                time_result = time_results_by_employee.get(result.employee_id)
                if (
                    time_result is None
                    or time_result.id != result.cutoff_result_id
                    or time_result.incomplete_time_source_count > 0
                ):
                    raise ValueError(
                        "Attendance results changed after payroll was calculated. Recalculate payroll before approval."
                    )

            cutoff.locked_at = approved_at
            cutoff.locked_by = actor_id
            cutoff.status = "LOCKED"
            cutoff.updated_at = approved_at
            cutoff.updated_by = actor_id
            cutoff.row_version += 1
            return PayrollCutoffLockState(
                cutoff_id=cutoff.id,
                locked=True,
                locked_at=cutoff.locked_at,
                locked_by=cutoff.locked_by,
            )

    async def unlock_payroll_cutoff(
        self,
        cutoff_id: UUID,
        actor_id: UUID,
        unlocked_at: datetime,
    ) -> PayrollCutoffLockState:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.scalar(
                select(PayrollCutoffModel)
                .where(
                    PayrollCutoffModel.id == cutoff_id,
                    PayrollCutoffModel.is_active.is_(True),
                )
                .with_for_update()
            )
            if cutoff is None:
                raise LookupError("Payroll cutoff not found.")
            if cutoff.locked_at is None and cutoff.status.upper() != "LOCKED":
                raise ValueError("This payroll cutoff is not finalized.")

            cutoff.locked_at = None
            cutoff.locked_by = None
            cutoff.status = "ACTIVE"
            cutoff.updated_at = unlocked_at
            cutoff.updated_by = actor_id
            cutoff.row_version += 1
            return PayrollCutoffLockState(
                cutoff_id=cutoff.id,
                locked=False,
                locked_at=None,
                locked_by=None,
            )
