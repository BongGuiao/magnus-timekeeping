"""Plans how newly uploaded schedule rows override an employee's approved assignments.

Each uploaded row owns its date window. Any approved assignment overlapping that window is
trimmed around it: the part before the window ends the day before, the part after the window
resumes the day after, and an assignment entirely inside the window is retired.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Iterable
from uuid import UUID

from app.filemaintenance.schedule.domain.entities.schedule_upload import ExistingScheduleAssignment
from app.filemaintenance.schedule.domain.schedule_upload_rules import periods_overlap

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class ScheduleOverride:
    row_no: int
    employee_id: UUID
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class AssignmentRevision:
    """New dates for an existing assignment, or its retirement when ``retire`` is set."""

    assignment: ExistingScheduleAssignment
    effective_from: date
    effective_to: date | None
    retire: bool = False


@dataclass(frozen=True)
class AssignmentContinuation:
    """The remainder of an existing assignment that resumes after an override window."""

    source: ExistingScheduleAssignment
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class ScheduleOverridePlan:
    revisions: tuple[AssignmentRevision, ...] = ()
    continuations: tuple[AssignmentContinuation, ...] = ()
    effects_by_row: dict[int, tuple[str, ...]] | None = None

    def effects_for(self, row_no: int) -> tuple[str, ...]:
        return (self.effects_by_row or {}).get(row_no, ())


@dataclass(frozen=True)
class _Segment:
    effective_from: date
    effective_to: date | None
    source: ExistingScheduleAssignment | None = None


def _describe_period(effective_from: date, effective_to: date | None) -> str:
    return f"{effective_from.isoformat()} to {effective_to.isoformat() if effective_to else 'open-ended'}"


def _describe_effect(segment: _Segment, override: ScheduleOverride, keeps_before: bool, keeps_after: bool) -> str:
    assert segment.source is not None
    label = f"{segment.source.schedule_code} ({_describe_period(segment.effective_from, segment.effective_to)})"
    if keeps_before and keeps_after:
        assert override.effective_to is not None
        return (
            f"Pauses schedule {label}: it ends on {(override.effective_from - _ONE_DAY).isoformat()} "
            f"and resumes on {(override.effective_to + _ONE_DAY).isoformat()}."
        )
    if keeps_before:
        return f"Ends schedule {label} on {(override.effective_from - _ONE_DAY).isoformat()}."
    if keeps_after:
        assert override.effective_to is not None
        return f"Moves the start of schedule {label} to {(override.effective_to + _ONE_DAY).isoformat()}."
    return f"Replaces schedule {label}."


def _apply_override(
    segments: list[_Segment], override: ScheduleOverride, effects: list[str]
) -> list[_Segment]:
    result: list[_Segment] = []
    for segment in segments:
        if not periods_overlap(
            segment.effective_from, segment.effective_to, override.effective_from, override.effective_to
        ):
            result.append(segment)
            continue
        if segment.source is None:
            raise ValueError("Uploaded rows for the same employee must not overlap.")

        keeps_before = segment.effective_from < override.effective_from
        keeps_after = override.effective_to is not None and (
            segment.effective_to is None or segment.effective_to > override.effective_to
        )
        if keeps_before:
            result.append(replace(segment, effective_to=override.effective_from - _ONE_DAY))
        if keeps_after:
            assert override.effective_to is not None
            result.append(replace(segment, effective_from=override.effective_to + _ONE_DAY))
        effects.append(_describe_effect(segment, override, keeps_before, keeps_after))

    result.append(_Segment(override.effective_from, override.effective_to))
    return sorted(result, key=lambda segment: segment.effective_from)


def plan_schedule_overrides(
    existing: Iterable[ExistingScheduleAssignment],
    overrides: Iterable[ScheduleOverride],
) -> ScheduleOverridePlan:
    existing_by_employee: dict[UUID, list[ExistingScheduleAssignment]] = defaultdict(list)
    for assignment in existing:
        existing_by_employee[assignment.employee_id].append(assignment)
    overrides_by_employee: dict[UUID, list[ScheduleOverride]] = defaultdict(list)
    for override in overrides:
        overrides_by_employee[override.employee_id].append(override)

    revisions: list[AssignmentRevision] = []
    continuations: list[AssignmentContinuation] = []
    effects_by_row: dict[int, tuple[str, ...]] = {}

    for employee_id, employee_overrides in overrides_by_employee.items():
        assignments = existing_by_employee.get(employee_id, [])
        segments = [
            _Segment(assignment.effective_from, assignment.effective_to, assignment)
            for assignment in assignments
        ]
        for override in sorted(employee_overrides, key=lambda item: (item.effective_from, item.row_no)):
            effects: list[str] = []
            segments = _apply_override(segments, override, effects)
            if effects:
                effects_by_row[override.row_no] = tuple(effects)

        for assignment in assignments:
            remaining = [segment for segment in segments if segment.source is assignment]
            if not remaining:
                revisions.append(
                    AssignmentRevision(
                        assignment, assignment.effective_from, assignment.effective_to, retire=True
                    )
                )
                continue
            first, *rest = remaining
            if (first.effective_from, first.effective_to) != (
                assignment.effective_from,
                assignment.effective_to,
            ):
                revisions.append(AssignmentRevision(assignment, first.effective_from, first.effective_to))
            continuations.extend(
                AssignmentContinuation(assignment, segment.effective_from, segment.effective_to)
                for segment in rest
            )

    return ScheduleOverridePlan(
        revisions=tuple(revisions),
        continuations=tuple(continuations),
        effects_by_row=effects_by_row,
    )
