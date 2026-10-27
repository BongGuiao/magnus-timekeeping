from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.payroll.application.benefit_inputs import (
    BenefitTypeInput,
    CutoffBenefitInput,
    CutoffBenefitUploadRow,
    EmployeeBenefitEntitlementInput,
    EmployeeBenefitDeductionInput,
)
from app.payroll.domain.entities.benefits import (
    BenefitType,
    CutoffBenefit,
    EmployeeBenefitEntitlement,
    EmployeeBenefitDeduction,
)
from app.payroll.infrastructure.db_model import (
    BenefitTypeModel,
    CutoffBenefitModel,
    EmployeeBenefitEntitlementModel,
    EmployeeBenefitDeductionModel,
)


def _benefit_type_entity(model: BenefitTypeModel) -> BenefitType:
    return BenefitType(
        id=model.id,
        payroll_group_id=model.payroll_group_id,
        code=model.code,
        name=model.name,
        category=model.category,
        tax_treatment=model.tax_treatment,
        withholding_timing=model.withholding_timing,
        is_active=model.is_active,
        created_at=model.created_at,
        created_by=model.created_by,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
        row_version=model.row_version,
        attendance_based=model.attendance_based,
        deduct_for_late=model.deduct_for_late,
        deduct_for_undertime=model.deduct_for_undertime,
        posting_schedule=model.posting_schedule,
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
        withholding_timing=model.withholding_timing,
        amount=Decimal(model.amount),
        notes=model.notes,
        attendance_based=model.attendance_based,
        deduct_for_late=model.deduct_for_late,
        deduct_for_undertime=model.deduct_for_undertime,
    )


def _employee_deduction_entity(
    model: EmployeeBenefitDeductionModel,
    benefit_type: BenefitTypeModel,
) -> EmployeeBenefitDeduction:
    return EmployeeBenefitDeduction(
        id=model.id,
        employee_id=model.employee_id,
        benefit_type_id=model.benefit_type_id,
        benefit_code=benefit_type.code,
        benefit_name=benefit_type.name,
        amount_per_occurrence=Decimal(model.amount_per_occurrence),
        schedule=model.schedule,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        is_active=model.is_active,
    )


def _employee_benefit_entitlement_entity(
    model: EmployeeBenefitEntitlementModel,
    benefit_type: BenefitTypeModel,
) -> EmployeeBenefitEntitlement:
    return EmployeeBenefitEntitlement(
        id=model.id,
        employee_id=model.employee_id,
        benefit_type_id=model.benefit_type_id,
        benefit_code=benefit_type.code,
        benefit_name=benefit_type.name,
        amount_per_occurrence=Decimal(model.amount_per_occurrence),
        schedule=model.schedule,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        is_active=model.is_active,
    )


class SqlAlchemyBenefitRepository:
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def list_benefit_types(self, payroll_group_id: UUID) -> list[BenefitType]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = await session.scalars(
                select(BenefitTypeModel)
                .where(BenefitTypeModel.payroll_group_id == payroll_group_id)
                .order_by(BenefitTypeModel.name)
            )
            return [_benefit_type_entity(model) for model in models]

    async def create_benefit_type(self, data: BenefitTypeInput) -> BenefitType:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = BenefitTypeModel(
                payroll_group_id=data.payroll_group_id,
                code=data.code,
                name=data.name,
                category=data.category,
                tax_treatment=data.tax_treatment,
                withholding_timing=data.withholding_timing,
                attendance_based=data.attendance_based,
                deduct_for_late=data.deduct_for_late,
                deduct_for_undertime=data.deduct_for_undertime,
                posting_schedule=data.posting_schedule,
                created_by=data.actor_id,
                updated_by=data.actor_id,
            )
            session.add(model)
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError("Benefit code already exists for this payroll group.") from error
            return _benefit_type_entity(model)

    async def update_benefit_type(
        self, benefit_type_id: UUID, data: BenefitTypeInput
    ) -> BenefitType:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(BenefitTypeModel)
                .where(BenefitTypeModel.id == benefit_type_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Benefit type not found.")
            if model.payroll_group_id != data.payroll_group_id:
                raise ValueError("A benefit type cannot be moved to another payroll group.")
            model.code = data.code
            model.name = data.name
            model.category = data.category
            model.tax_treatment = data.tax_treatment
            model.withholding_timing = data.withholding_timing
            model.attendance_based = data.attendance_based
            model.deduct_for_late = data.deduct_for_late
            model.deduct_for_undertime = data.deduct_for_undertime
            model.posting_schedule = data.posting_schedule
            model.updated_by = data.actor_id
            model.updated_at = datetime.now(timezone.utc)
            model.row_version += 1
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError("Benefit code already exists for this payroll group.") from error
            return _benefit_type_entity(model)

    async def set_benefit_type_active(
        self, benefit_type_id: UUID, is_active: bool, actor_id: UUID
    ) -> BenefitType:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(BenefitTypeModel)
                .where(BenefitTypeModel.id == benefit_type_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Benefit type not found.")
            model.is_active = is_active
            model.updated_by = actor_id
            model.updated_at = datetime.now(timezone.utc)
            model.row_version += 1
            await session.flush()
            return _benefit_type_entity(model)

    async def list_cutoff_benefits(self, cutoff_id: UUID) -> list[CutoffBenefit]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = await session.scalars(
                select(CutoffBenefitModel)
                .where(CutoffBenefitModel.cutoff_id == cutoff_id)
                .order_by(CutoffBenefitModel.employee_id, CutoffBenefitModel.benefit_name)
            )
            return [_cutoff_benefit_entity(model) for model in models]

    async def save_cutoff_benefit(
        self, data: CutoffBenefitInput, entry_id: UUID | None = None
    ) -> CutoffBenefit:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.scalar(
                select(PayrollCutoffModel)
                .where(PayrollCutoffModel.id == data.cutoff_id)
                .with_for_update()
            )
            if cutoff is None or not cutoff.is_active:
                raise LookupError("Payroll cutoff not found.")
            if cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED":
                raise ValueError("Benefits cannot be changed for a locked payroll cutoff.")
            cutoff_result = await session.scalar(
                select(EmployeeCutoffResultModel.id).where(
                    EmployeeCutoffResultModel.cutoff_id == data.cutoff_id,
                    EmployeeCutoffResultModel.employee_id == data.employee_id,
                )
            )
            if cutoff_result is None:
                raise ValueError("The employee does not have a time result in this cutoff.")
            benefit_type = await session.scalar(
                select(BenefitTypeModel).where(
                    BenefitTypeModel.id == data.benefit_type_id,
                    BenefitTypeModel.payroll_group_id == cutoff.payroll_group_id,
                    BenefitTypeModel.is_active.is_(True),
                )
            )
            if benefit_type is None:
                raise ValueError("Select an active benefit type from this payroll group.")
            model = None
            if entry_id is not None:
                model = await session.scalar(
                    select(CutoffBenefitModel)
                    .where(
                        CutoffBenefitModel.id == entry_id,
                        CutoffBenefitModel.cutoff_id == data.cutoff_id,
                        CutoffBenefitModel.employee_id == data.employee_id,
                    )
                    .with_for_update()
                )
                if model is None:
                    raise LookupError("Benefit entry not found for this cutoff and employee.")
            else:
                model = CutoffBenefitModel(
                    cutoff_id=data.cutoff_id,
                    employee_id=data.employee_id,
                    benefit_type_id=benefit_type.id,
                    created_by=data.actor_id,
                    row_version=1,
                )
                session.add(model)
            model.benefit_type_id = benefit_type.id
            model.benefit_code = benefit_type.code
            model.benefit_name = benefit_type.name
            model.category = benefit_type.category
            model.tax_treatment = benefit_type.tax_treatment
            model.withholding_timing = benefit_type.withholding_timing
            model.attendance_based = benefit_type.attendance_based
            model.deduct_for_late = benefit_type.deduct_for_late
            model.deduct_for_undertime = benefit_type.deduct_for_undertime
            model.amount = data.amount
            model.notes = data.notes
            model.updated_by = data.actor_id
            model.updated_at = datetime.now(timezone.utc)
            if entry_id is not None:
                model.row_version += 1
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError(
                    "This employee already has an entry for that benefit in this cutoff."
                ) from error
            return _cutoff_benefit_entity(model)

    async def upload_cutoff_benefits(
        self,
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        actor_id: UUID,
    ) -> tuple[int, int]:
        return await self._upload_cutoff_entries(
            cutoff_id, rows, actor_id, "benefit", False
        )

    async def upload_cutoff_deductions(
        self,
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        actor_id: UUID,
    ) -> tuple[int, int]:
        return await self._upload_cutoff_entries(
            cutoff_id, rows, actor_id, "deduction", True
        )

    async def _upload_cutoff_entries(
        self,
        cutoff_id: UUID,
        rows: tuple[CutoffBenefitUploadRow, ...],
        actor_id: UUID,
        category: str,
        is_deduction: bool,
    ) -> tuple[int, int]:
        error_name = "deductions" if is_deduction else "benefits"
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
                raise ValueError(
                    f"{error_name.capitalize()} cannot be changed for a locked payroll cutoff."
                )

            employee_rows = await session.execute(
                select(EmployeeModel.id, EmployeeModel.employee_no)
                .join(
                    EmployeeCutoffResultModel,
                    EmployeeCutoffResultModel.employee_id == EmployeeModel.id,
                )
                .where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
            )
            employees_by_no = {
                employee_no.strip().upper(): employee_id
                for employee_id, employee_no in employee_rows
            }
            type_query = select(BenefitTypeModel).where(
                BenefitTypeModel.payroll_group_id == cutoff.payroll_group_id,
                BenefitTypeModel.is_active.is_(True),
            )
            if is_deduction:
                type_query = type_query.where(
                    BenefitTypeModel.category == "EMPLOYEE_DEDUCTION"
                )
            else:
                type_query = type_query.where(
                    BenefitTypeModel.category != "EMPLOYEE_DEDUCTION"
                )
            benefit_models = list((await session.scalars(type_query)).all())
            benefits_by_code = {item.code.strip().upper(): item for item in benefit_models}

            resolved_rows: list[tuple[UUID, BenefitTypeModel, CutoffBenefitUploadRow]] = []
            for row_number, row in enumerate(rows, start=2):
                employee_id = employees_by_no.get(row.employee_no.strip().upper())
                if employee_id is None:
                    raise ValueError(
                        f"Row {row_number}: employee {row.employee_no!r} does not have a time result in this cutoff."
                    )
                benefit_type = benefits_by_code.get(row.benefit_code.strip().upper())
                if benefit_type is None:
                    raise ValueError(
                        f"Row {row_number}: {category} type "
                        f"{row.benefit_code!r} is not active for this payroll group."
                    )
                resolved_rows.append((employee_id, benefit_type, row))

            existing_models = list(
                (
                    await session.scalars(
                        select(CutoffBenefitModel)
                        .where(CutoffBenefitModel.cutoff_id == cutoff_id)
                        .with_for_update()
                    )
                ).all()
            )
            existing_by_key = {
                (item.employee_id, item.benefit_type_id): item
                for item in existing_models
            }
            created_count = 0
            updated_count = 0
            now = datetime.now(timezone.utc)
            for employee_id, benefit_type, row in resolved_rows:
                model = existing_by_key.get((employee_id, benefit_type.id))
                if model is None:
                    model = CutoffBenefitModel(
                        cutoff_id=cutoff_id,
                        employee_id=employee_id,
                        benefit_type_id=benefit_type.id,
                        created_by=actor_id,
                        row_version=1,
                    )
                    session.add(model)
                    created_count += 1
                else:
                    model.row_version += 1
                    updated_count += 1
                model.benefit_code = benefit_type.code
                model.benefit_name = benefit_type.name
                model.category = benefit_type.category
                model.tax_treatment = benefit_type.tax_treatment
                model.withholding_timing = benefit_type.withholding_timing
                model.attendance_based = benefit_type.attendance_based
                model.deduct_for_late = benefit_type.deduct_for_late
                model.deduct_for_undertime = benefit_type.deduct_for_undertime
                model.amount = row.amount
                model.notes = row.notes
                model.updated_by = actor_id
                model.updated_at = now
            await session.flush()
            return created_count, updated_count

    async def delete_cutoff_benefit(self, entry_id: UUID) -> None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(CutoffBenefitModel)
                .where(CutoffBenefitModel.id == entry_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Benefit entry not found.")
            cutoff = await session.scalar(
                select(PayrollCutoffModel)
                .where(PayrollCutoffModel.id == model.cutoff_id)
                .with_for_update()
            )
            if cutoff is None or cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED":
                raise ValueError("Benefits cannot be changed for a locked payroll cutoff.")
            await session.delete(model)

    async def list_employee_deductions(
        self, payroll_group_id: UUID
    ) -> list[EmployeeBenefitDeduction]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            rows = (
                await session.execute(
                    select(EmployeeBenefitDeductionModel, BenefitTypeModel)
                    .join(
                        BenefitTypeModel,
                        BenefitTypeModel.id == EmployeeBenefitDeductionModel.benefit_type_id,
                    )
                    .where(BenefitTypeModel.payroll_group_id == payroll_group_id)
                    .order_by(
                        EmployeeBenefitDeductionModel.employee_id,
                        BenefitTypeModel.name,
                    )
                )
            ).all()
            return [
                _employee_deduction_entity(deduction, benefit_type)
                for deduction, benefit_type in rows
            ]

    async def save_employee_deduction(
        self,
        data: EmployeeBenefitDeductionInput,
        deduction_id: UUID | None = None,
    ) -> EmployeeBenefitDeduction:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            benefit_type = await session.scalar(
                select(BenefitTypeModel)
                .where(
                    BenefitTypeModel.id == data.benefit_type_id,
                    BenefitTypeModel.is_active.is_(True),
                    BenefitTypeModel.category == "EMPLOYEE_DEDUCTION",
                )
            )
            if benefit_type is None:
                raise ValueError("Select an active employee-deduction benefit type.")
            model = None
            if deduction_id is not None:
                model = await session.scalar(
                    select(EmployeeBenefitDeductionModel)
                    .where(EmployeeBenefitDeductionModel.id == deduction_id)
                    .with_for_update()
                )
                if model is None:
                    raise LookupError("Employee benefit deduction not found.")
            else:
                model = EmployeeBenefitDeductionModel(
                    employee_id=data.employee_id,
                    benefit_type_id=benefit_type.id,
                    created_by=data.actor_id,
                    updated_by=data.actor_id,
                )
                session.add(model)
            model.employee_id = data.employee_id
            model.benefit_type_id = benefit_type.id
            model.amount_per_occurrence = data.amount_per_occurrence
            model.schedule = data.schedule
            model.effective_from = data.effective_from
            model.effective_to = data.effective_to
            model.is_active = True
            model.updated_by = data.actor_id
            model.updated_at = datetime.now(timezone.utc)
            if deduction_id is not None:
                model.row_version += 1
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError(
                    "An employee deduction already exists for this benefit type."
                ) from error
            return _employee_deduction_entity(model, benefit_type)

    async def set_employee_deduction_active(
        self,
        deduction_id: UUID,
        is_active: bool,
        actor_id: UUID,
    ) -> EmployeeBenefitDeduction:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(EmployeeBenefitDeductionModel)
                .where(EmployeeBenefitDeductionModel.id == deduction_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Employee benefit deduction not found.")
            benefit_type = await session.get(BenefitTypeModel, model.benefit_type_id)
            if benefit_type is None:
                raise RuntimeError("The employee deduction's benefit type could not be loaded.")
            model.is_active = is_active
            model.updated_by = actor_id
            model.updated_at = datetime.now(timezone.utc)
            model.row_version += 1
            await session.flush()
            return _employee_deduction_entity(model, benefit_type)

    async def list_employee_benefit_entitlements(
        self, payroll_group_id: UUID
    ) -> list[EmployeeBenefitEntitlement]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            rows = (
                await session.execute(
                    select(EmployeeBenefitEntitlementModel, BenefitTypeModel)
                    .join(
                        BenefitTypeModel,
                        BenefitTypeModel.id == EmployeeBenefitEntitlementModel.benefit_type_id,
                    )
                    .where(
                        BenefitTypeModel.payroll_group_id == payroll_group_id,
                        BenefitTypeModel.category != "EMPLOYEE_DEDUCTION",
                    )
                    .order_by(
                        EmployeeBenefitEntitlementModel.employee_id,
                        BenefitTypeModel.name,
                    )
                )
            ).all()
            return [
                _employee_benefit_entitlement_entity(entitlement, benefit_type)
                for entitlement, benefit_type in rows
            ]

    async def save_employee_benefit_entitlement(
        self,
        data: EmployeeBenefitEntitlementInput,
        entitlement_id: UUID | None = None,
    ) -> EmployeeBenefitEntitlement:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            benefit_type = await session.scalar(
                select(BenefitTypeModel)
                .where(
                    BenefitTypeModel.id == data.benefit_type_id,
                    BenefitTypeModel.is_active.is_(True),
                    BenefitTypeModel.category != "EMPLOYEE_DEDUCTION",
                )
            )
            if benefit_type is None:
                raise ValueError("Select an active benefit type.")

            model = None
            if entitlement_id is not None:
                model = await session.scalar(
                    select(EmployeeBenefitEntitlementModel)
                    .where(EmployeeBenefitEntitlementModel.id == entitlement_id)
                    .with_for_update()
                )
                if model is None:
                    raise LookupError("Employee benefit entitlement not found.")
            else:
                model = EmployeeBenefitEntitlementModel(
                    employee_id=data.employee_id,
                    benefit_type_id=benefit_type.id,
                    created_by=data.actor_id,
                    updated_by=data.actor_id,
                )
                session.add(model)

            model.employee_id = data.employee_id
            model.benefit_type_id = benefit_type.id
            model.amount_per_occurrence = data.amount_per_occurrence
            model.schedule = data.schedule
            model.effective_from = data.effective_from
            model.effective_to = data.effective_to
            model.is_active = True
            model.updated_by = data.actor_id
            model.updated_at = datetime.now(timezone.utc)
            if entitlement_id is not None:
                model.row_version += 1
            try:
                await session.flush()
            except IntegrityError as error:
                raise ValueError(
                    "An employee entitlement already exists for this benefit type."
                ) from error
            return _employee_benefit_entitlement_entity(model, benefit_type)

    async def set_employee_benefit_entitlement_active(
        self,
        entitlement_id: UUID,
        is_active: bool,
        actor_id: UUID,
    ) -> EmployeeBenefitEntitlement:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(EmployeeBenefitEntitlementModel)
                .where(EmployeeBenefitEntitlementModel.id == entitlement_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Employee benefit entitlement not found.")
            benefit_type = await session.get(BenefitTypeModel, model.benefit_type_id)
            if benefit_type is None:
                raise RuntimeError("The entitlement's benefit type could not be loaded.")
            model.is_active = is_active
            model.updated_by = actor_id
            model.updated_at = datetime.now(timezone.utc)
            model.row_version += 1
            await session.flush()
            return _employee_benefit_entitlement_entity(model, benefit_type)
