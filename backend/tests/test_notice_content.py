import base64
import unittest
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from PIL import Image

from app.attendance.domain.notice_authorization import is_authorized_hr_head
from app.attendance.domain.notice_content import (
    MAX_SIGNATURE_BYTES, render_notice, response_deadline, sanitize_template, validate_signature,
)


def signature():
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "black").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class NoticeContentTests(unittest.TestCase):
    def test_sanitizes_active_content_and_escapes_values(self):
        template = sanitize_template(
            '<p onclick="evil()">{{employee_name}}</p><script>evil()</script>'
            '<a href="https://example.com">link</a><img src="https://example.com/x">'
            '{{signature}}'
        )
        values = {key: "" for key in (
            "employee_name", "employee_no", "employee_position", "notice_date", "period_start",
            "period_end", "late_dates", "attendance_records", "signatory_name", "signatory_title",
        )}
        values["employee_name"] = '<img src=x onerror=alert(1)>'
        result = render_notice(template, values, signature())
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", result)
        self.assertNotIn("<script", result)
        self.assertNotIn("evil()", result)
        self.assertNotIn("https://", result)
        self.assertIn('<img alt="HR head signature" src="data:image/png;base64,', result)

    def test_attendance_record_lines_are_escaped_before_line_breaks(self):
        values = {key: "" for key in (
            "employee_name", "employee_no", "employee_position", "notice_date", "period_start",
            "period_end", "late_dates", "attendance_records", "signatory_name", "signatory_title",
        )}
        values["attendance_records"] = "One\n<script>Two</script>"
        result = render_notice("{{attendance_records}}{{signature}}", values, signature())
        self.assertIn("One<br>&lt;script&gt;Two&lt;/script&gt;", result)

    def test_return_to_work_fields_are_module_scoped_and_escaped(self):
        source = "<p>{{employee_address}}</p><p>{{last_attendance_date}}</p>{{expected_return_date}}{{signature}}"
        template = sanitize_template(source, "RETURN_TO_WORK")
        rendered = render_notice(template, {
            "employee_address": "First line\n<script>Second</script>",
            "last_attendance_date": "2026-10-01",
            "expected_return_date": "2026-10-20",
        }, signature(), "RETURN_TO_WORK")
        self.assertIn("First line<br>&lt;script&gt;Second&lt;/script&gt;", rendered)
        with self.assertRaises(ValueError):
            sanitize_template(source, "TARDINESS")
        with self.assertRaises(ValueError):
            render_notice(template, {"employee_address": "Incomplete"}, signature(), "RETURN_TO_WORK")

    def test_return_to_work_rejects_tardiness_only_fields(self):
        with self.assertRaises(ValueError):
            sanitize_template("{{late_dates}}{{signature}}", "RETURN_TO_WORK")

    def test_unknown_or_missing_placeholders_and_bad_signature_rejected(self):
        for template in ("<p>{{unknown}}{{signature}}</p>", "<p>Missing signature</p>", "{{BAD}}{{signature}}"):
            with self.subTest(template=template), self.assertRaises(ValueError):
                sanitize_template(template)
        values = {key: "" for key in (
            "employee_name", "employee_no", "employee_position", "notice_date", "period_start",
            "period_end", "late_dates", "attendance_records", "signatory_name", "signatory_title",
        )}
        with self.assertRaises(ValueError):
            render_notice(sanitize_template("{{signature}}"), values, base64.b64encode(b"not png").decode())
        with self.assertRaises(ValueError):
            validate_signature("A" * (4 * ((MAX_SIGNATURE_BYTES + 2) // 3) + 1))

    def test_deadline_is_end_of_fifth_manila_calendar_day(self):
        received = datetime(2026, 2, 28, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(response_deadline(received), datetime(2026, 3, 6, 15, 59, 59, 999999, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            response_deadline(datetime(2026, 2, 28))

    def test_hr_head_requires_both_configured_identity_and_current_hr_role(self):
        head, other = uuid4(), uuid4()
        self.assertTrue(is_authorized_hr_head(head, ["HR_ADMIN"], str(head)))
        self.assertFalse(is_authorized_hr_head(other, ["HR_ADMIN"], str(head)))
        self.assertFalse(is_authorized_hr_head(head, ["SUPERVISOR"], str(head)))
        with self.assertRaises(ValueError):
            is_authorized_hr_head(head, ["HR_ADMIN"], None)
        with self.assertRaises(ValueError):
            is_authorized_hr_head(head, ["HR_ADMIN"], "invalid")
