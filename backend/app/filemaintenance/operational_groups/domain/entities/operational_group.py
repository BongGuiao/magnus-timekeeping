from dataclasses import dataclass
from uuid import UUID


@dataclass
class OperationalGroupEntity:
    company_id: UUID
    operational_group: str
    display_name: str
    sort_order: int
    is_active: bool
