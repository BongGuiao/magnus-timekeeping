from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
import logging
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.core import security as security_service
from app.core.config import settings

logger = logging.getLogger(__name__)

MOBILE_MARKERS = ("android", "iphone", "ipad", "ipod", "mobile", "iemobile", "opera mini", "blackberry")
optional_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AttendanceClockPolicy:
    channel: str  # "kiosk" | "mobile" | "desktop"
    geofence_required: bool
    client_ip: str | None
    kiosk_user_id: str | None = None
    is_native: bool = False

    def as_metadata(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "client_ip": self.client_ip,
            "kiosk_user_id": self.kiosk_user_id,
        }


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_networks(value: str) -> list[IPv4Network | IPv6Network]:
    networks: list[IPv4Network | IPv6Network] = []
    for item in _split_csv(value):
        try:
            networks.append(ip_network(item, strict=False))
        except ValueError:
            logger.error("Ignoring invalid ATTENDANCE_KIOSK_ALLOWED_IPS entry: %s", item)
    return networks


def is_mobile_user_agent(user_agent: str | None) -> bool:
    return bool(user_agent and any(marker in user_agent.lower() for marker in MOBILE_MARKERS))


def get_client_ip(request: Request) -> str | None:
    # nginx overwrites X-Real-IP with $remote_addr, so clients cannot spoof it; the backend is not exposed directly.
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None


def _decode_role_and_user(credentials: HTTPAuthorizationCredentials | None) -> tuple[str | None, str | None]:
    if credentials is None:
        return None, None
    try:
        claims = security_service.decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        return None, None
    return claims.get("role"), claims.get("sub")


def resolve_attendance_clock_policy(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer_scheme),
) -> AttendanceClockPolicy:
    client_ip = get_client_ip(request)

    is_native_attendance_client = request.headers.get("x-attendance-client", "").strip().lower() == "native"
    if is_native_attendance_client or is_mobile_user_agent(request.headers.get("user-agent")):
        # Phones are never kiosks, even when they reach the API from an allow-listed IP or carry an admin token.
        return AttendanceClockPolicy("mobile", True, client_ip, is_native=is_native_attendance_client)

    if settings.ATTENDANCE_KIOSK_ENABLED and client_ip:
        networks = _parse_networks(settings.ATTENDANCE_KIOSK_ALLOWED_IPS)
        try:
            address = ip_address(client_ip)
        except ValueError:
            address = None
        if address is not None and any(address in network for network in networks):
            required_roles = _split_csv(settings.ATTENDANCE_KIOSK_REQUIRED_ROLES)
            role, user_id = _decode_role_and_user(credentials)
            if not required_roles or role in required_roles:
                return AttendanceClockPolicy("kiosk", False, client_ip, user_id)

    return AttendanceClockPolicy("desktop", settings.ATTENDANCE_GEOFENCE_ENFORCE_DESKTOP, client_ip)
