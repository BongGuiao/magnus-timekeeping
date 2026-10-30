from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class OperationalGroupEntity:
    company_id: UUID
    operational_group: str
    display_name: str
    sort_order: int
    is_active: bool
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
