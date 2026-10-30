import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

OFFLINE_LIFETIME = timedelta(hours=24)
OFFLINE_ACTIONS = (
    "clock_in", "clock_out",
    "first_break_out_at", "first_break_in_at",
    "meal_break_out_at", "meal_break_in_at",
    "second_break_out_at", "second_break_in_at",
    "ot_break_out_at", "ot_break_in_at",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def event_message(payload_json: str) -> bytes:
    return ("magnus-offline-punch-v1\n" + payload_json).encode()


def parse_instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Offline timestamps must contain a timezone.")
    return result.astimezone(timezone.utc)


def validate_capture(payload: dict, permit: dict, received_at: datetime) -> None:
    captured_at = parse_instant(payload["captured_at"])
    if not parse_instant(permit["issued_at"]) <= captured_at < parse_instant(permit["expires_at"]):
        raise ValueError("The offline authorization was not valid at capture time.")
    if captured_at > received_at + timedelta(minutes=2):
        raise ValueError("The offline punch is in the future.")
    gps_at = parse_instant(payload["gps_at"])
    if abs((captured_at - gps_at).total_seconds()) > 60:
        raise ValueError("The offline punch needs a fresh GPS reading.")
    for key in ("latitude", "longitude", "accuracy"):
        if not isinstance(payload.get(key), (int, float)) or not math.isfinite(payload[key]):
            raise ValueError("Offline GPS coordinates and accuracy must be finite numbers.")
    if not -90 <= payload["latitude"] <= 90 or not -180 <= payload["longitude"] <= 180:
        raise ValueError("Offline GPS coordinates are invalid.")
    if payload["accuracy"] <= 0:
        raise ValueError("Offline GPS accuracy must be positive.")
    if payload["action"] not in OFFLINE_ACTIONS:
        raise ValueError("Unknown offline attendance action.")
    if not isinstance(payload.get("sequence"), int) or payload["sequence"] < 1:
        raise ValueError("Offline event sequence must be positive.")


def circle_contains(fence: dict, latitude: float, longitude: float, accuracy: float) -> bool:
    if fence["shape"] != "CIRCLE" or accuracy > fence["maximum_gps_accuracy_meters"]:
        return False
    radius = fence.get("radius_meters")
    if radius is None or radius <= 0 or fence.get("latitude") is None or fence.get("longitude") is None:
        return False
    lat1, lat2 = math.radians(latitude), math.radians(fence["latitude"])
    dlat = lat2 - lat1
    dlon = math.radians(fence["longitude"] - longitude)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    distance = 6371008.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0, 1 - a)))
    return distance + accuracy <= radius
