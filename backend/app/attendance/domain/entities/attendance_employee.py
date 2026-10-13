from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass
class AttendanceEmployee:
    id: UUID
    employee_no: str
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    suffix: Optional[str] = None
    preferred_name: Optional[str] = None

    @property
    def display_name(self) -> str:
        preferred = self.preferred_name.strip() if self.preferred_name else ""
        return preferred or " ".join(
            part for part in (self.first_name, self.middle_name, self.last_name, self.suffix) if part
        )
