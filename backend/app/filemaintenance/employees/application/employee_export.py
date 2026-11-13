import csv
from collections.abc import Iterable, Sequence
from io import StringIO


EMPLOYEE_EXPORT_FIELDS = (
    "employee_no", "first_name", "middle_name", "last_name", "suffix",
    "preferred_name", "birth_date", "gender_code", "personal_email",
    "mobile_no", "photo_reference", "record_status", "is_active",
)
PERSONAL_DETAILS_EXPORT_FIELDS = (
    "bank_account_no", "sss_no", "pagibig_no", "philhealth_no", "tin_no",
    "civil_status", "address_line_1", "address_line_2", "region",
    "province", "city_municipality", "barangay", "postal_code",
    "psgc_region_code", "psgc_province_code", "psgc_city_code", "psgc_barangay_code",
)


def employee_export_csv(rows: Iterable[Sequence[object]]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow((*EMPLOYEE_EXPORT_FIELDS, *PERSONAL_DETAILS_EXPORT_FIELDS))
    for row in rows:
        values = []
        for value in row:
            text = "" if value is None else str(value)
            # Quoting alone does not prevent spreadsheets from evaluating formulas.
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
                text = "'" + text
            values.append(text)
        writer.writerow(values)
    return "\ufeff" + output.getvalue()
