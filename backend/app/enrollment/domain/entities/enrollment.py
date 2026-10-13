from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class EnrollmentStatus(str, Enum):
    PENDING = "pending"
    ENROLLED = "enrolled"
    FAILED = "failed"


@dataclass
class FaceEnrollmentEntity:
    employee_id: UUID
    # Numeric face embedding vector produced by the recognition model (e.g. 128-d/512-d)
    face_encoding: list[float]
    status: EnrollmentStatus = EnrollmentStatus.PENDING
    image_path: Optional[str] = None
    failure_reason: Optional[str] = None
    enrolled_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    # None until persisted; the DB assigns the id on insert
    id: Optional[UUID] = None
