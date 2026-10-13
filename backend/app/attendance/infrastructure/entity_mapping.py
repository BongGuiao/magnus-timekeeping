from dataclasses import fields
from typing import Any, TypeVar

from app.attendance.domain.entities.attendance_employee import AttendanceEmployee

T = TypeVar("T")


def copy_fields(source: Any, entity_cls: type[T]) -> T:
    """Builds a dataclass entity from a same-named-attribute source such as an ORM row."""
    return entity_cls(**{field.name: getattr(source, field.name) for field in fields(entity_cls)})


def to_attendance_employee(model: Any) -> AttendanceEmployee:
    return copy_fields(model, AttendanceEmployee)
