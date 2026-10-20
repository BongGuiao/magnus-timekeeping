from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
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
    PayrollBenefitLine,
    PayrollContributionLine,
    PayrollGroupPolicy,
)
from app.payroll.domain.entities.benefits import (
    CutoffBenefit,
    is_benefit_due,
    is_employee_deduction_due,
)
from app.payroll.domain.entities.net_payroll import NetPayrollInputs, OpeningYtdBalance
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    ContributionProgram,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
)
from app.payroll.domain.services.net_payroll import REQUIRED_CONTRIBUTION_PROGRAMS
from app.payroll.domain.assignment_coverage import require_exact_assignment_coverage
from app.payroll.infrastructure.db_model import (
    EmployeeCompensationModel,
    BenefitTypeModel,
    CutoffBenefitModel,
    EmployeeBenefitEntitlementModel,
    EmployeeBenefitDeductionModel,
    GrossPayResultModel,
    GrossPayRunModel,
    PayrollOpeningYtdBalanceModel,
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
    )


def _tax_schedule_entity(model: WithholdingTaxScheduleModel) -> WithholdingTaxSchedule:
    return WithholdingTaxSchedule(
        id=model.id,
        schedule_name=model.schedule_name,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        tax_exempt_benefit_limit=Decimal(model.tax_exempt_benefit_limit),
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
            result_models = await session.scalars(
                select(EmployeeCutoffResultModel)
                .where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
                .order_by(EmployeeCutoffResultModel.employee_id)
            )
            employees = tuple(
                CutoffEmployeeTime(
                    employee_id=result.employee_id,
                    cutoff_result_id=result.id,
                    employee_confirmation_status=result.employee_confirmation_status,
                    supervisor_status=result.supervisor_status,
                    hr_status=result.hr_status,
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
                payroll_group=PayrollGroupPolicy(
                    payroll_group_id=group.id,
                    rate_type=group.rate_type,
                    standard_minutes_per_day=group.standard_minutes_per_day,
                    annual_divisor=(
                        Decimal(group.annual_divisor)
                        if group.annual_divisor is not None
                        else None
                    ),
                ),
                employees=employees,
            )

    async def load_covering_compensation(
        self,
        employee_id: UUID,
        payroll_group_id: UUID,
        period_start: date,
        period_end: date,
    ) -> Compensation | None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = list(
                (
                    await session.scalars(
                        select(EmployeeCompensationModel)
                        .where(
                            EmployeeCompensationModel.employee_id == employee_id,
                            EmployeeCompensationModel.payroll_group_id == payroll_group_id,
                            EmployeeCompensationModel.is_active.is_(True),
                            EmployeeCompensationModel.effective_from <= period_start,
                            or_(
                                EmployeeCompensationModel.effective_to.is_(None),
                                EmployeeCompensationModel.effective_to >= period_end,
                            ),
                        )
                        .limit(2)
                    )
                ).all()
            )
            if len(models) != 1:
                return None
            assignments = list(
                (
                    await session.scalars(
                        select(EmploymentAssignmentModel.id)
                        .join(
                            PayrollGroupModel,
                            PayrollGroupModel.id == EmploymentAssignmentModel.payroll_group_id,
                        )
                        .where(
                            EmploymentAssignmentModel.employee_id == employee_id,
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
                        .limit(2)
                    )
                ).all()
            )
            return _compensation_entity(models[0]) if len(assignments) == 1 else None

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
                            "amount": str(line.amount),
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

    async def load_net_payroll_inputs(
        self, cutoff_id: UUID, employee_id: UUID
    ) -> NetPayrollInputs:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.get(PayrollCutoffModel, cutoff_id)
            if cutoff is None or not cutoff.is_active:
                raise LookupError("Payroll cutoff not found.")
            benefit_models = await session.scalars(
                select(CutoffBenefitModel).where(
                    CutoffBenefitModel.cutoff_id == cutoff_id,
                    CutoffBenefitModel.employee_id == employee_id,
                ).order_by(CutoffBenefitModel.id)
            )
            benefits = tuple(_cutoff_benefit_entity(item) for item in benefit_models)

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
            manual_benefit_types = {item.benefit_type_id for item in benefits}
            scheduled_deductions = (
                await session.execute(
                    select(EmployeeBenefitDeductionModel, BenefitTypeModel)
                    .join(
                        BenefitTypeModel,
                        BenefitTypeModel.id == EmployeeBenefitDeductionModel.benefit_type_id,
                    )
                    .where(
                        EmployeeBenefitDeductionModel.employee_id == employee_id,
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
            ).all()
            for deduction, benefit_type in scheduled_deductions:
                if (
                    not is_employee_deduction_due(deduction.schedule, cutoff_number)
                    or benefit_type.id in manual_benefit_types
                ):
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
                        amount=Decimal(deduction.amount_per_occurrence),
                        notes=f"Recurring deduction ({deduction.schedule.lower().replace('_', ' ')})",
                    ),
                )
            scheduled_entitlements = (
                await session.execute(
                    select(EmployeeBenefitEntitlementModel, BenefitTypeModel)
                    .join(
                        BenefitTypeModel,
                        BenefitTypeModel.id == EmployeeBenefitEntitlementModel.benefit_type_id,
                    )
                    .where(
                        EmployeeBenefitEntitlementModel.employee_id == employee_id,
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
            ).all()
            for entitlement, benefit_type in scheduled_entitlements:
                if (
                    not is_benefit_due(benefit_type.posting_schedule, cutoff_number)
                    or benefit_type.id in manual_benefit_types
                ):
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
                        amount=Decimal(entitlement.amount_per_occurrence),
                        notes=(
                            f"Recurring benefit ({benefit_type.posting_schedule.lower().replace('_', ' ')})"
                        ),
                        attendance_based=benefit_type.attendance_based,
                        deduct_for_late=benefit_type.deduct_for_late,
                        deduct_for_undertime=benefit_type.deduct_for_undertime,
                    ),
                )
            attendance = await session.scalar(
                select(EmployeeCutoffResultModel).where(
                    EmployeeCutoffResultModel.cutoff_id == cutoff_id,
                    EmployeeCutoffResultModel.employee_id == employee_id,
                )
            )
            if attendance is None:
                raise RuntimeError("Employee cutoff attendance facts could not be loaded.")
            previous_month_employee: dict[ContributionProgram, Decimal] = {
                code: Decimal(0) for code in REQUIRED_CONTRIBUTION_PROGRAMS
            }
            previous_month_employer: dict[ContributionProgram, Decimal] = {
                code: Decimal(0) for code in REQUIRED_CONTRIBUTION_PROGRAMS
            }
            earlier_cutoff_ids = cutoff_ids[: max(0, cutoff_number - 1)]
            if earlier_cutoff_ids:
                earlier_results = await session.scalars(
                    select(GrossPayResultModel)
                    .join(GrossPayRunModel, GrossPayRunModel.id == GrossPayResultModel.run_id)
                    .where(
                        GrossPayRunModel.is_current.is_(True),
                        GrossPayResultModel.employee_id == employee_id,
                        GrossPayResultModel.status == "READY",
                        GrossPayRunModel.cutoff_id.in_(earlier_cutoff_ids),
                    )
                )
                for result in earlier_results:
                    for line in result.contribution_lines or []:
                        code = line["program_code"]
                        if code in previous_month_employee:
                            previous_month_employee[code] += Decimal(line["employee_amount"])
                            previous_month_employer[code] += Decimal(line["employer_amount"])

            tax_year_start = date(cutoff.period_end.year, 1, 1)
            opening_model = await _current_opening_ytd_balance(
                session,
                employee_id,
                cutoff.period_end.year,
            )
            opening_taxable = (
                Decimal(opening_model.taxable_income) if opening_model is not None else Decimal(0)
            )
            opening_tax = (
                Decimal(opening_model.tax_withheld) if opening_model is not None else Decimal(0)
            )
            opening_limited_benefits = (
                Decimal(opening_model.exempt_limited_benefits)
                if opening_model is not None else Decimal(0)
            )
            ytd_rows = list((await session.execute(
                select(
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
                    GrossPayResultModel.employee_id == employee_id,
                    GrossPayResultModel.status == "READY",
                )
            )).all())
            prior_taxable = opening_taxable
            prior_tax = opening_tax
            prior_limited_benefits = opening_limited_benefits
            for taxable, tax, limited_benefits in ytd_rows:
                prior_taxable += Decimal(taxable or 0)
                prior_tax += Decimal(tax or 0)
                prior_limited_benefits += Decimal(limited_benefits or 0)

            return NetPayrollInputs(
                benefits=benefits,
                contribution_brackets=contribution_brackets,
                tax_schedule=tax_schedule,
                tax_brackets=tax_brackets,
                monthly_cutoff_count=len(monthly_cutoffs),
                cutoff_number_in_month=cutoff_number,
                prior_month_employee_contributions=previous_month_employee,
                prior_month_employer_contributions=previous_month_employer,
                prior_ytd_taxable_income=prior_taxable,
                prior_ytd_withholding_tax=prior_tax,
                prior_ytd_limited_exempt_benefits=prior_limited_benefits,
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
