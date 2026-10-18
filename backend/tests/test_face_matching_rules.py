import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from app.attendance.application.use_case import ClockAttendanceInputDTO, ClockAttendanceUseCase
from app.auth.domain.entities.user import UserEntity
from app.core import face_recognition_service
from app.enrollment.application.use_case import EnrollFaceUseCase
from app.enrollment.domain.entities.enrollment import FaceEnrollmentEntity
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity


def vector(offset: float) -> list[float]:
    """128-d encoding whose Euclidean distance from vector(0) equals offset."""
    return [offset] + [0.0] * 127


class FakeUow:
    def __init__(self, repos):
        self.repos = repos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get_repo(self, entity, model):
        return self.repos[entity]


class FindBestMatchTests(unittest.TestCase):
    def test_default_threshold_comes_from_settings(self):
        employee_id = uuid4()
        with patch.object(face_recognition_service, "match_threshold", return_value=0.5):
            self.assertIsNone(face_recognition_service.find_best_match(vector(0), [(employee_id, vector(0.55))]))
            self.assertEqual(
                face_recognition_service.find_best_match(vector(0), [(employee_id, vector(0.45))]),
                (employee_id, 0.45),
            )

    def test_closest_employee_wins_across_all_enrollments(self):
        selected, other = uuid4(), uuid4()
        match = face_recognition_service.find_best_match(
            vector(0), [(selected, vector(0.4)), (other, vector(0.2))], threshold=0.5,
        )
        self.assertEqual(match[0], other)


class ClockFaceVerificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.employee_id, self.other_id = uuid4(), uuid4()
        self.enrollments = []
        repos = {
            UserEntity: SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
                employee_id=self.employee_id, is_active=True, account_status="ACTIVE",
            ))),
            EmployeeEntity: SimpleNamespace(find_one=AsyncMock(return_value=SimpleNamespace(
                id=self.employee_id, is_active=True, record_status="ACTIVE",
            ))),
            FaceEnrollmentEntity: SimpleNamespace(find_all=AsyncMock(side_effect=lambda *a, **k: self.enrollments)),
        }
        face = SimpleNamespace(
            extract_face_encoding=Mock(return_value=vector(0)),
            find_best_match=lambda candidate, known: face_recognition_service.find_best_match(
                candidate, known, threshold=0.5,
            ),
        )
        self.use_case = ClockAttendanceUseCase(FakeUow(repos), face)

    async def clock(self):
        return await self.use_case._execute(ClockAttendanceInputDTO(
            user_id=uuid4(), image_bytes=b"image", enforce_geofence=False,
        ))

    async def test_rejects_face_closer_to_another_employee(self):
        self.enrollments = [
            SimpleNamespace(employee_id=self.employee_id, face_encoding=vector(0.4)),
            SimpleNamespace(employee_id=self.other_id, face_encoding=vector(0.1)),
        ]
        with self.assertRaisesRegex(ValueError, "does not match the selected employee"):
            await self.clock()

    async def test_rejects_face_outside_threshold(self):
        self.enrollments = [SimpleNamespace(employee_id=self.employee_id, face_encoding=vector(0.55))]
        with self.assertRaisesRegex(ValueError, "Face not recognized"):
            await self.clock()

    async def test_requires_enrollment_for_selected_employee(self):
        self.enrollments = [SimpleNamespace(employee_id=self.other_id, face_encoding=vector(0.1))]
        with self.assertRaisesRegex(ValueError, "no active face enrollment"):
            await self.clock()


class EnrollmentFaceGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.employee_id, self.other_id = uuid4(), uuid4()
        self.face = SimpleNamespace(
            match_threshold=lambda: 0.5,
            face_distances=face_recognition_service.face_distances,
        )
        self.use_case = EnrollFaceUseCase(None, self.face)
        self.employee_repo = SimpleNamespace(find_one=AsyncMock(return_value=SimpleNamespace(employee_no="EMP-0009")))
        self.uow = FakeUow({EmployeeEntity: self.employee_repo})

    async def guard(self, enrolled, candidate):
        repo = SimpleNamespace(find_all=AsyncMock(return_value=enrolled))
        await self.use_case._ensure_face_belongs_to_employee(self.uow, repo, self.employee_id, candidate)

    async def test_accepts_first_sample_and_consistent_samples(self):
        await self.guard([], vector(0))
        await self.guard([SimpleNamespace(employee_id=self.employee_id, face_encoding=vector(0.3))], vector(0))

    async def test_rejects_sample_that_differs_from_existing_samples(self):
        enrolled = [
            SimpleNamespace(employee_id=self.employee_id, face_encoding=vector(0.2)),
            SimpleNamespace(employee_id=self.employee_id, face_encoding=vector(0.7)),
        ]
        with self.assertRaisesRegex(ValueError, "does not match the employee's existing"):
            await self.guard(enrolled, vector(0))

    async def test_rejects_face_already_enrolled_for_another_employee(self):
        enrolled = [SimpleNamespace(employee_id=self.other_id, face_encoding=vector(0.3))]
        with self.assertRaisesRegex(ValueError, r"another employee \(EMP-0009\)"):
            await self.guard(enrolled, vector(0))


if __name__ == "__main__":
    unittest.main()
