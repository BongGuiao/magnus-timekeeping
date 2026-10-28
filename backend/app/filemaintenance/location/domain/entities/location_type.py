from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class LocationTypeEntity:
    company_id: UUID
    location_type: str
    display_name: str
    sort_order: int
    is_default: bool
    is_active: bool
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
