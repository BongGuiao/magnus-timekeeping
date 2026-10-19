import unittest

from app.filemaintenance.schedule.infrastructure.schedule_upload_csv import (
    CsvScheduleUploadReader,
    schedule_upload_csv_template,
)


class CsvScheduleUploadReaderTests(unittest.TestCase):
    def setUp(self):
        self.reader = CsvScheduleUploadReader()

    def test_reads_rows_with_bom_and_normalized_headers(self):
        content = (
            "\ufeffEmployee Code,Schedule_Code,ASSIGNMENT_TYPE,effective_from,effective_to\r\n"
            "E001,DAY,REGULAR,2026-11-01,\r\n"
            ",,,,\r\n"
            "E002,NIGHT,REGULAR,2026-11-02,2026-11-30\r\n"
        ).encode("utf-8")

        result = self.reader.read(content)

        self.assertEqual(result.file_errors, ())
        self.assertEqual([row.row_no for row in result.rows], [2, 4])
        self.assertEqual(result.rows[0].employee_code, "E001")
        self.assertEqual(result.rows[0].rest_day_pattern_code, "")
        self.assertEqual(result.rows[1].effective_to, "2026-11-30")

    def test_falls_back_to_windows_encoding(self):
        content = "employee_code,schedule_code,assignment_type,effective_from,reason\nE001,DAY,REGULAR,2026-11-01,Señor\n"

        result = self.reader.read(content.encode("cp1252"))

        self.assertEqual(result.rows[0].reason, "Señor")

    def test_reports_header_problems(self):
        result = self.reader.read(b"employee_code,employee_code,shift\nE001,E001,X\n")

        joined = " ".join(result.file_errors)
        self.assertIn("Duplicate column(s): employee_code", joined)
        self.assertIn("Unknown column(s): shift", joined)
        self.assertIn("Missing required column(s): schedule_code", joined)
        self.assertEqual(result.rows, ())

    def test_reports_rows_with_extra_values(self):
        result = self.reader.read(
            b"employee_code,schedule_code,assignment_type,effective_from\nE001,DAY,REGULAR,2026-11-01,extra\n"
        )

        self.assertIn("Row 2 has more values", result.file_errors[0])

    def test_empty_file(self):
        self.assertEqual(self.reader.read(b"").file_errors, ("The file is empty.",))

    def test_template_header_round_trips(self):
        result = self.reader.read(schedule_upload_csv_template().encode("utf-8"))

        self.assertEqual(result.file_errors, ())
        self.assertEqual(result.rows, ())


if __name__ == "__main__":
    unittest.main()
