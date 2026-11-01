def decode_csv_text(content: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def normalize_csv_header(value: str) -> str:
    return "_".join(value.strip().lower().split())
