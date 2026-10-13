from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AuditLogCreate(BaseModel):
    user_id: str
    action: str
    resource: str
    resource_id: str
    old_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
