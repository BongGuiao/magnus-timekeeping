from typing import Any

AUTO_ABSENCE_KEY = "automatic_absence"


def has_automatic_absence_marker(metadata: Any) -> bool:
    return isinstance(metadata, dict) and isinstance(metadata.get(AUTO_ABSENCE_KEY), dict)
