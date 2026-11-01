import csv
import io
from dataclasses import dataclass

from app.core.csv_upload import decode_csv_text, normalize_csv_header

AMOUNT_COLUMNS = {
    "opening_balance": "opening_minutes",
    "granted": "granted_minutes",
    "accrued": "accrued_minutes",
    "carryover": "carryover_minutes",
    "adjustment": "adjustment_minutes",
    "used": "used_minutes",
    "reserved": "reserved_minutes",
    "expired": "expired_minutes",
    "converted": "converted_minutes",
}
CSV_COLUMNS = ("employee_no", "leave_code", "entitlement_year", *AMOUNT_COLUMNS)
MAX_ROWS_PER_UPLOAD = 1000


@dataclass(frozen=True)
class RawEntitlementUploadRow:
    row_no: int
    values: dict[str, str]


@dataclass(frozen=True)
class EntitlementUploadFile:
    rows: tuple[RawEntitlementUploadRow, ...] = ()
    file_errors: tuple[str, ...] = ()


def entitlement_upload_csv_template() -> str:
    return ",".join(CSV_COLUMNS) + "\r\n"


def read_entitlement_upload_csv(content: bytes) -> EntitlementUploadFile:
    text = decode_csv_text(content)
    if text is None:
        return EntitlementUploadFile(file_errors=("The file is not a readable text CSV file.",))

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        first_row = next(reader, None)
        if first_row is None:
            return EntitlementUploadFile(file_errors=("The file is empty.",))

        header = [normalize_csv_header(value) for value in first_row]
        errors: list[str] = []
        duplicates = sorted({column for column in header if column and header.count(column) > 1})
        if duplicates:
            errors.append(f"Duplicate column(s): {', '.join(duplicates)}.")
        if any(not column for column in header):
            errors.append("Column headings cannot be blank.")
        unknown = [column for column in header if column and column not in CSV_COLUMNS]
        if unknown:
            errors.append(f"Unknown column(s): {', '.join(unknown)}.")
        missing = [column for column in CSV_COLUMNS if column not in header]
        if missing:
            errors.append(f"Missing required column(s): {', '.join(missing)}.")
        if errors:
            return EntitlementUploadFile(file_errors=tuple(errors))

        rows: list[RawEntitlementUploadRow] = []
        previous_line = reader.line_num
        for values in reader:
            row_no = previous_line + 1
            previous_line = reader.line_num
            if not any(value.strip() for value in values):
                continue
            if len(values) > len(header):
                errors.append(f"Row {row_no} has more values than there are columns.")
                continue
            rows.append(RawEntitlementUploadRow(row_no, dict(zip(header, values))))
            if len(rows) > MAX_ROWS_PER_UPLOAD:
                errors.append(f"The file cannot contain more than {MAX_ROWS_PER_UPLOAD} rows.")
                break

        if not rows and not errors:
            errors.append("The file must contain at least one entitlement row.")
        return EntitlementUploadFile(rows=tuple(rows), file_errors=tuple(errors))
    except csv.Error as error:
        return EntitlementUploadFile(file_errors=(f"The CSV file is malformed: {error}.",))
