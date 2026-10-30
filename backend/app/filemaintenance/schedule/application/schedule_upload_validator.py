from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Sequence
from uuid import UUID

from app.filemaintenance.schedule.application.schedule_upload_ports import ScheduleUploadLookups
from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    RawScheduleUploadRow,
    ResolvedScheduleUploadRow,
    ScheduleUploadRow,
    ScheduleUploadRowResult,
    ScheduleUploadValidation,
    SupervisorEmployee,
)
from app.filemaintenance.schedule.domain.schedule_timeline import (
    ScheduleOverride,
    ScheduleOverridePlan,
    plan_schedule_overrides,
)
from app.filemaintenance.schedule.domain.schedule_upload_rules import (
    MAX_ROWS_PER_UPLOAD,
    MAX_CODE_LENGTH,
    find_overlapping_rows,
    parse_row,
    rest_day_pattern_errors,
    template_errors,
)


@dataclass(frozen=True)
class ScheduleUploadEvaluation:
    validation: ScheduleUploadValidation
    resolved_rows: tuple[ResolvedScheduleUploadRow, ...] = ()
    plan: ScheduleOverridePlan = ScheduleOverridePlan()


def _row_result(
    raw: RawScheduleUploadRow,
    parsed: ScheduleUploadRow | None,
    errors: Sequence[str],
    resolved: ResolvedScheduleUploadRow | None = None,
    effects: Sequence[str] = (),
) -> ScheduleUploadRowResult:
    return ScheduleUploadRowResult(
        row_no=raw.row_no,
        employee_code=parsed.employee_code if parsed else raw.employee_code.strip(),
        schedule_code=parsed.schedule_code if parsed else raw.schedule_code.strip(),
        assignment_type=parsed.assignment_type if parsed else raw.assignment_type.strip(),
        effective_from=parsed.effective_from if parsed else None,
        effective_to=parsed.effective_to if parsed else None,
        rest_day_pattern_code=parsed.rest_day_pattern_code if parsed else raw.rest_day_pattern_code.strip() or None,
        reason=parsed.reason if parsed else raw.reason.strip() or None,
        employee_name=resolved.employee.employee_name if resolved else None,
        schedule_name=resolved.template.schedule_name if resolved else None,
        errors=tuple(errors),
        effects=tuple(effects),
        supervisor_employee_code=raw.supervisor_employee_code.strip() or None,
    )


class ScheduleUploadValidator:
    """Validates uploaded rows against the supervisor's team and current schedule data."""

    def __init__(self, lookups: ScheduleUploadLookups):
        self._lookups = lookups

    async def evaluate(
        self,
        *,
        supervisor_employee_id: UUID | None,
        raw_rows: Sequence[RawScheduleUploadRow],
        today: date,
        file_errors: Sequence[str] = (),
        supervisors_by_code: dict[str, SupervisorEmployee] | None = None,
    ) -> ScheduleUploadEvaluation:
        if file_errors:
            return ScheduleUploadEvaluation(ScheduleUploadValidation(file_errors=tuple(file_errors)))
        if not raw_rows:
            return ScheduleUploadEvaluation(
                ScheduleUploadValidation(file_errors=("The file does not contain any schedule rows.",))
            )
        if len(raw_rows) > MAX_ROWS_PER_UPLOAD:
            return ScheduleUploadEvaluation(
                ScheduleUploadValidation(
                    file_errors=(
                        f"The file has {len(raw_rows)} rows; upload at most {MAX_ROWS_PER_UPLOAD} rows per file.",
                    )
                )
            )

        parsed_by_row = {raw.row_no: parse_row(raw, today) for raw in raw_rows}
        errors_by_row: dict[int, list[str]] = {
            row_no: list(parsed.errors) for row_no, parsed in parsed_by_row.items()
        }
        parsed_rows = [parsed.row for parsed in parsed_by_row.values() if parsed.row is not None]
        for row_no, overlap_errors in find_overlapping_rows(parsed_rows).items():
            errors_by_row[row_no].extend(overlap_errors)

        if supervisors_by_code is None:
            if supervisor_employee_id is None:
                raise ValueError("A supervisor is required for a team schedule upload.")
            resolved_by_row = await self._resolve(supervisor_employee_id, parsed_rows, today, errors_by_row)
        else:
            rows_by_supervisor: dict[UUID, list[ScheduleUploadRow]] = defaultdict(list)
            for raw in raw_rows:
                code = raw.supervisor_employee_code.strip()
                if not code:
                    errors_by_row[raw.row_no].append("supervisor_employee_code is required.")
                elif len(code) > MAX_CODE_LENGTH:
                    errors_by_row[raw.row_no].append(
                        f"supervisor_employee_code must be at most {MAX_CODE_LENGTH} characters."
                    )
                elif code not in supervisors_by_code:
                    errors_by_row[raw.row_no].append(f"Supervisor {code} was not found or is not active.")
                elif (parsed := parsed_by_row[raw.row_no].row) is not None:
                    rows_by_supervisor[supervisors_by_code[code].employee_id].append(parsed)
            resolved_by_row = {}
            for supervisor_id, rows in rows_by_supervisor.items():
                resolved_by_row.update(await self._resolve(supervisor_id, rows, today, errors_by_row))

        valid_resolved = [
            resolved for row_no, resolved in resolved_by_row.items() if not errors_by_row[row_no]
        ]
        plan = plan_schedule_overrides(
            await self._lookups.list_approved_assignments(
                {resolved.employee.employee_id for resolved in valid_resolved}
            ) if valid_resolved else [],
            [
                ScheduleOverride(
                    row_no=resolved.row.row_no,
                    employee_id=resolved.employee.employee_id,
                    effective_from=resolved.row.effective_from,
                    effective_to=resolved.row.effective_to,
                )
                for resolved in valid_resolved
            ],
        )

        results = tuple(
            _row_result(
                raw,
                parsed_by_row[raw.row_no].row,
                errors_by_row[raw.row_no],
                resolved_by_row.get(raw.row_no),
                plan.effects_for(raw.row_no),
            )
            for raw in raw_rows
        )
        validation = ScheduleUploadValidation(rows=results)
        return ScheduleUploadEvaluation(
            validation=validation,
            resolved_rows=tuple(valid_resolved) if validation.is_valid else (),
            plan=plan if validation.is_valid else ScheduleOverridePlan(),
        )

    async def _resolve(
        self,
        supervisor_employee_id: UUID,
        rows: Sequence[ScheduleUploadRow],
        today: date,
        errors_by_row: dict[int, list[str]],
    ) -> dict[int, ResolvedScheduleUploadRow]:
        if not rows:
            return {}
        team = await self._lookups.find_team_employees(
            supervisor_employee_id, {row.employee_code for row in rows}, today
        )
        employees_by_code = defaultdict(list)
        for employee in team:
            employees_by_code[employee.employee_code].append(employee)

        templates = await self._lookups.find_schedule_templates(
            {employee.company_id for employee in team}, {row.schedule_code for row in rows}
        )
        templates_by_key = {(template.company_id, template.schedule_code): template for template in templates}

        pattern_codes = {row.rest_day_pattern_code for row in rows if row.rest_day_pattern_code}
        patterns = await self._lookups.find_rest_day_patterns(pattern_codes) if pattern_codes else []
        patterns_by_code = {pattern.pattern_code: pattern for pattern in patterns}

        resolved: dict[int, ResolvedScheduleUploadRow] = {}
        for row in rows:
            errors = errors_by_row[row.row_no]
            matches = employees_by_code.get(row.employee_code, [])
            if not matches:
                errors.append(
                    f"Employee {row.employee_code} is not an active direct report of the submitting supervisor."
                )
                continue
            if len(matches) > 1:
                errors.append(
                    f"Employee {row.employee_code} has more than one active company assignment; "
                    "ask HR to assign this schedule."
                )
                continue
            employee = matches[0]

            template = templates_by_key.get((employee.company_id, row.schedule_code))
            if template is None:
                errors.append(f"Schedule {row.schedule_code} does not exist in the employee's company.")
            else:
                errors.extend(template_errors(template, row))

            pattern = None
            if row.rest_day_pattern_code:
                pattern = patterns_by_code.get(row.rest_day_pattern_code)
                if pattern is None:
                    errors.append(f"Rest day pattern {row.rest_day_pattern_code} does not exist.")
                else:
                    errors.extend(rest_day_pattern_errors(pattern))

            if template is not None:
                resolved[row.row_no] = ResolvedScheduleUploadRow(row, employee, template, pattern, supervisor_employee_id)
        return resolved
