import unittest
from io import BytesIO
from math import hypot
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import numpy as np
from PIL import Image

from app.attendance.application.use_case import ClockAttendanceInputDTO, ClockAttendanceUseCase
from app.auth.domain.entities.user import UserEntity
from app.core import face_recognition_service
from app.enrollment.application.use_case import EnrollFaceUseCase, FaceSimilarityConflict, SimilarityOverride
from app.enrollment.domain.entities.enrollment import FaceEnrollmentEntity
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity


def vector(offset: float) -> list[float]:
    """Non-zero 128-d encoding whose distance from vector(0) equals offset."""
    return [offset, 1.0] + [0.0] * 126


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
    def test_invalid_encodings_cannot_participate_in_matching(self):
        invalid = (
            [0.0] * 128, [float("nan")] + [0.0] * 127,
            [float("inf")] + [0.0] * 127, [float("-inf")] + [0.0] * 127,
            [1.0], [], [[1.0] * 128], [None] * 128, ["invalid"] * 128,
        )
        for index, encoding in enumerate(invalid):
            with self.subTest(case=index):
                with self.assertRaisesRegex(ValueError, "Captured face encoding is invalid"):
                    face_recognition_service.face_distances(encoding, [vector(0)])
                with self.assertRaisesRegex(ValueError, "Stored face encoding is invalid"):
                    face_recognition_service.find_best_match(vector(0), [(uuid4(), encoding)])

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
            vector(0), [(selected, vector(0.4)), (other, vector(0.2))], threshold=0.5, margin=0.05,
        )
        self.assertEqual(match[0], other)

    def test_near_tie_between_employees_is_rejected_as_ambiguous(self):
        selected, other = uuid4(), uuid4()
        known = [(selected, vector(0.3)), (selected, vector(0.6)), (other, vector(0.33))]
        with self.assertLogs("app.core.face_recognition_service", level="INFO"):
            self.assertIsNone(face_recognition_service.find_best_match(vector(0), known, threshold=0.5, margin=0.05))
        self.assertEqual(
            face_recognition_service.find_best_match(vector(0), known, threshold=0.5, margin=0.02),
            (selected, 0.3),
        )
        # Several samples of the same employee are never treated as a competing identity.
        self.assertEqual(
            face_recognition_service.find_best_match(
                vector(0), [(selected, vector(0.3)), (selected, vector(0.31))], threshold=0.5, margin=0.05,
            ),
            (selected, 0.3),
        )


class FaceExtractionTests(unittest.TestCase):
    def test_each_upload_is_decoded_as_rgb_and_gets_its_own_encoding(self):
        photos = []
        for color in ((255, 0, 0, 255), (0, 0, 255, 255)):
            image = BytesIO()
            Image.new("RGBA", (2, 2), color).save(image, format="PNG")
            photos.append(image.getvalue())
        with patch.object(
            face_recognition_service.face_recognition, "face_encodings",
            side_effect=[[np.asarray(vector(0.1))], [np.asarray(vector(0.8))]],
        ) as encode:
            results = [face_recognition_service.extract_face_encoding(photo) for photo in photos]
        self.assertEqual(results, [vector(0.1), vector(0.8)])
        self.assertEqual(encode.call_args_list[0].args[0][0, 0].tolist(), [255, 0, 0])
        self.assertEqual(encode.call_args_list[1].args[0][0, 0].tolist(), [0, 0, 255])

    def test_detector_failure_or_invalid_output_never_becomes_an_enrollment(self):
        for encodings, message in (
            ([], "No face detected"),
            ([np.asarray(vector(0)), np.asarray(vector(1))], "Multiple faces"),
            ([np.zeros(128)], "Captured face encoding is invalid"),
            ([np.full(128, np.nan)], "Captured face encoding is invalid"),
            ([np.ones(127)], "Captured face encoding is invalid"),
        ):
            with self.subTest(message=message), \
                    patch.object(face_recognition_service.face_recognition, "load_image_file"), \
                    patch.object(face_recognition_service.face_recognition, "face_encodings", return_value=encodings), \
                    self.assertRaisesRegex(ValueError, message):
                face_recognition_service.extract_face_encoding(b"capture")


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
                candidate, known, threshold=0.5, margin=0.05,
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

    async def test_rejects_punch_when_another_employee_is_nearly_as_close(self):
        self.enrollments = [
            SimpleNamespace(employee_id=self.employee_id, face_encoding=vector(0.3)),
            SimpleNamespace(employee_id=self.other_id, face_encoding=vector(0.32)),
        ]
        with self.assertLogs("app.core.face_recognition_service", level="INFO"), \
                self.assertRaisesRegex(ValueError, "Face not recognized"):
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
            find_best_match=face_recognition_service.find_best_match,
        )
        self.use_case = EnrollFaceUseCase(None, self.face)
        self.employee_repo = SimpleNamespace(find_one=AsyncMock(return_value=SimpleNamespace(employee_no="EMP-0009")))
        self.uow = FakeUow({EmployeeEntity: self.employee_repo})
        self.uow.session = SimpleNamespace(scalar=AsyncMock(return_value=None))
        margin = patch.object(face_recognition_service, "match_margin", return_value=0.05)
        margin.start()
        self.addCleanup(margin.stop)

    async def guard(self, enrolled, candidate):
        repo = SimpleNamespace(find_all=AsyncMock(return_value=enrolled))
        return await self.use_case._ensure_face_belongs_to_employee(self.uow, repo, self.employee_id, candidate)

    async def test_clear_own_match_can_continue_an_active_hr_approval(self):
        approval = SimpleNamespace(id=uuid4(), approved_by=uuid4())
        self.uow.session.scalar.return_value = approval
        enrolled = [
            SimpleNamespace(id=uuid4(), employee_id=self.employee_id, face_encoding=vector(0)),
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.4)),
        ]
        conflicts, source = await self.guard(enrolled, vector(0.01))
        self.assertIs(source, approval)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].employee_id, self.other_id)
        self.assertAlmostEqual(conflicts[0].distance, 0.39)

    async def test_approval_does_not_automatically_resolve_ambiguous_or_competing_matches(self):
        self.uow.session.scalar.return_value = SimpleNamespace(id=uuid4(), approved_by=uuid4())
        enrolled = [
            SimpleNamespace(id=uuid4(), employee_id=self.employee_id, face_encoding=vector(0)),
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.4)),
        ]
        for offset in (0.18, 0.2, 0.3):
            with self.subTest(offset=offset), self.assertRaises(FaceSimilarityConflict):
                await self.guard(enrolled, vector(offset))
        self.uow.session.scalar.assert_not_awaited()

    async def test_continuation_obeys_the_configured_winning_margin(self):
        approval = SimpleNamespace(id=uuid4(), approved_by=uuid4())
        self.uow.session.scalar.return_value = approval
        enrolled = [
            SimpleNamespace(id=uuid4(), employee_id=self.employee_id, face_encoding=vector(0)),
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.5)),
        ]
        with patch.object(face_recognition_service, "match_margin", return_value=0.125):
            _, source = await self.guard(enrolled, vector(0.1875))
            self.assertIs(source, approval)
            with self.assertRaises(FaceSimilarityConflict):
                await self.guard(enrolled, vector(0.1876))

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
        sample_id = uuid4()
        enrolled = [
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.4)),
            SimpleNamespace(id=sample_id, employee_id=self.other_id, face_encoding=vector(0.3)),
        ]
        with self.assertLogs("app.enrollment.application.use_case", level="WARNING") as logs, \
                self.assertRaisesRegex(ValueError, r"another employee \(EMP-0009\).*Closest distance 0\.300; limit 0\.500"):
            await self.guard(enrolled, vector(0))
        message = logs.records[0].getMessage()
        for field in (
            f"requested_employee_id={self.employee_id}", f"matched_employee_id={self.other_id}",
            "matched_employee_no=EMP-0009", f"matched_sample_id={sample_id}", "distance=0.3",
            "threshold=0.5", "candidate_norm=1.0", f"matched_norm={hypot(0.3, 1.0)!r}",
            "override_requested=False",
        ):
            self.assertIn(field, message)
        self.assertNotIn(str(vector(0.3)), message)

    async def test_matching_hr_override_returns_every_similar_employee(self):
        enrolled = [
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.3)),
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.45)),
        ]
        repo = SimpleNamespace(find_all=AsyncMock(return_value=enrolled))
        conflicts, source = await self.use_case._ensure_face_belongs_to_employee(
            self.uow, repo, self.employee_id, vector(0), SimilarityOverride(frozenset({"EMP-0009"}), "Verified"),
        )
        self.assertIsNone(source)
        self.assertEqual([(item.employee_id, item.distance) for item in conflicts], [(self.other_id, 0.3)])

    async def test_strict_protection_remains_even_when_own_sample_is_closer(self):
        enrolled = [
            SimpleNamespace(id=uuid4(), employee_id=self.employee_id, face_encoding=vector(0)),
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.502)),
        ]
        with self.assertRaisesRegex(ValueError, "No sample was saved"):
            await self.guard(enrolled, vector(0.01))

    async def test_conflict_uses_nearest_other_sample_not_first_record(self):
        first_id = uuid4()
        enrolled = [
            SimpleNamespace(id=uuid4(), employee_id=first_id, face_encoding=vector(0.8)),
            SimpleNamespace(id=uuid4(), employee_id=self.other_id, face_encoding=vector(0.2)),
        ]
        with self.assertRaisesRegex(ValueError, "Similarity does not confirm"):
            await self.guard(enrolled, vector(0))
        criterion = self.employee_repo.find_one.await_args.args[0]
        self.assertEqual(criterion.right.value, self.other_id)


if __name__ == "__main__":
    unittest.main()
