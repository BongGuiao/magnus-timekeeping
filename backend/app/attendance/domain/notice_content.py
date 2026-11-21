import base64
import binascii
import html
import re
from datetime import datetime, time, timedelta, timezone
from io import BytesIO
from typing import Literal
from zoneinfo import ZoneInfo

import nh3
from PIL import Image, UnidentifiedImageError

MANILA = ZoneInfo("Asia/Manila")
MAX_TEMPLATE_BYTES = 100_000
MAX_SIGNATURE_BYTES = 1_000_000
NoticeTemplateModule = Literal["TARDINESS", "RETURN_TO_WORK"]
COMMON_PLACEHOLDERS = frozenset({
    "employee_name", "employee_no", "employee_position", "notice_date",
    "signatory_name", "signatory_title", "signature",
})
MODULE_PLACEHOLDERS: dict[NoticeTemplateModule, frozenset[str]] = {
    "TARDINESS": COMMON_PLACEHOLDERS | {"period_start", "period_end", "late_dates", "attendance_records"},
    "RETURN_TO_WORK": COMMON_PLACEHOLDERS | {
        "employee_address", "salutation", "last_attendance_date", "consecutive_absence_days",
        "expected_return_date", "signatory_contact",
    },
}
PLACEHOLDER = re.compile(r"{{\s*([a-z_]+)\s*}}")
TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "div", "span",
    "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
    "h1", "h2", "h3", "h4", "blockquote", "hr",
}


def sanitize_template(source: str, module: NoticeTemplateModule = "TARDINESS") -> str:
    if not source.strip() or len(source.encode("utf-8")) > MAX_TEMPLATE_BYTES:
        raise ValueError("The HTML template is empty or too large.")
    if module not in MODULE_PLACEHOLDERS:
        raise ValueError("Unsupported notice template module.")
    sanitized = nh3.clean(
        source, tags=TAGS, attributes={}, clean_content_tags={"script", "style", "iframe", "object", "svg", "math"},
        strip_comments=True,
    )
    fields = set(PLACEHOLDER.findall(sanitized))
    if fields - MODULE_PLACEHOLDERS[module] or "signature" not in fields:
        raise ValueError("The template contains fields not available for this module or is missing {{signature}}.")
    if "{{" in PLACEHOLDER.sub("", sanitized) or "}}" in PLACEHOLDER.sub("", sanitized):
        raise ValueError("The template contains an invalid placeholder.")
    return sanitized


def validate_signature(value: str) -> str:
    if len(value) > 4 * ((MAX_SIGNATURE_BYTES + 2) // 3):
        raise ValueError("The signature image is too large.")
    try:
        image_bytes = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("The signature must be a base64-encoded PNG image.") from error
    if not image_bytes or len(image_bytes) > MAX_SIGNATURE_BYTES:
        raise ValueError("The signature image is empty or too large.")
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format != "PNG" or image.width > 4096 or image.height > 4096:
                raise ValueError("The signature must be a PNG no larger than 4096 by 4096 pixels.")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("The signature is not a valid PNG image.") from error
    return base64.b64encode(image_bytes).decode("ascii")


def render_notice(
    template: str,
    values: dict[str, str],
    signature: str,
    module: NoticeTemplateModule = "TARDINESS",
) -> str:
    template = sanitize_template(template, module)
    needed_fields = set(PLACEHOLDER.findall(template)) - {"signature"}
    if needed_fields - values.keys():
        raise ValueError("Notice field values are incomplete.")
    if set(values) - (MODULE_PLACEHOLDERS[module] - {"signature"}):
        raise ValueError("Notice field values contain fields not available for this module.")
    validated_signature = validate_signature(signature)
    escaped = {key: html.escape(value, quote=True) for key, value in values.items()}
    for key in ("attendance_records", "employee_address", "signatory_contact"):
        if key in escaped:
            escaped[key] = escaped[key].replace("\n", "<br>")
    escaped["signature"] = f'<img alt="HR head signature" src="data:image/png;base64,{validated_signature}">'
    return PLACEHOLDER.sub(lambda match: escaped[match.group(1)], template)


def response_deadline(received_at: datetime) -> datetime:
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("Receipt time must include a timezone.")
    deadline_date = received_at.astimezone(MANILA).date() + timedelta(days=5)
    return datetime.combine(deadline_date, time.max, MANILA).astimezone(timezone.utc)
