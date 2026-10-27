from dataclasses import dataclass
from uuid import UUID


@dataclass
class OrgUnitTypeEntity:
    company_id: UUID
    org_unit_type: str
    display_name: str
    sort_order: int
    is_default: bool
    is_active: bool
