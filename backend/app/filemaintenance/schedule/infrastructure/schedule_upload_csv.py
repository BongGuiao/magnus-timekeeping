import csv
import io

from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    RawScheduleUploadRow,
    ScheduleUploadFile,
)
from app.filemaintenance.schedule.domain.schedule_upload_rules import CSV_COLUMNS, REQUIRED_COLUMNS

# Excel on Windows saves "CSV (Comma delimited)" as cp1252 and "CSV UTF-8" with a BOM.
_ENCODINGS = ("utf-8-sig", "cp1252")


def _normalize_header(value: str) -> str:
    return "_".join(value.strip().lower().split())


def _decode(content: bytes) -> str | None:
    for encoding in _ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def schedule_upload_csv_template() -> str:
    return ",".join(CSV_COLUMNS) + "\r\n"


class CsvScheduleUploadReader:
    """Reads the supervisor schedule upload CSV format into raw rows."""

    def read(self, content: bytes) -> ScheduleUploadFile:
        text = _decode(content)
        if text is None:
            return ScheduleUploadFile(file_errors=("The file is not a readable text CSV file.",))

        try:
            records = list(csv.reader(io.StringIO(text, newline="")))
        except csv.Error as error:
            return ScheduleUploadFile(file_errors=(f"The CSV file is malformed: {error}.",))
        if not records:
            return ScheduleUploadFile(file_errors=("The file is empty.",))

        header = [_normalize_header(value) for value in records[0]]
        file_errors = self._header_errors(header)
        if file_errors:
            return ScheduleUploadFile(file_errors=tuple(file_errors))

        rows: list[RawScheduleUploadRow] = []
        for line_no, values in enumerate(records[1:], start=2):
            if not any(value.strip() for value in values):
                continue
            if len(values) > len(header) and any(value.strip() for value in values[len(header):]):
                file_errors.append(f"Row {line_no} has more values than there are columns.")
                continue
            record = dict(zip(header, values))
            rows.append(RawScheduleUploadRow(row_no=line_no, **{column: record.get(column, "") for column in CSV_COLUMNS}))
        return ScheduleUploadFile(rows=tuple(rows), file_errors=tuple(file_errors))

    @staticmethod
    def _header_errors(header: list[str]) -> list[str]:
        errors: list[str] = []
        duplicates = sorted({column for column in header if column and header.count(column) > 1})
        if duplicates:
            errors.append(f"Duplicate column(s): {', '.join(duplicates)}.")
        unknown = [column for column in header if column and column not in CSV_COLUMNS]
        if unknown:
            errors.append(
                f"Unknown column(s): {', '.join(unknown)}. Allowed columns: {', '.join(CSV_COLUMNS)}."
            )
        missing = [column for column in CSV_COLUMNS if column in REQUIRED_COLUMNS and column not in header]
        if missing:
            errors.append(f"Missing required column(s): {', '.join(missing)}.")
        return errors
