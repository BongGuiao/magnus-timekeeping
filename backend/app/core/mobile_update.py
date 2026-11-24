import logging
import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.generics.mapper import ResponseEnvelope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Mobile updates"])
VERSION_PATTERN = re.compile(r"(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})")


class MobileUpdate(BaseModel):
    version: str
    url: str
    release_notes: str


@router.get("/mobile-update", response_model=ResponseEnvelope[MobileUpdate | None])
async def get_mobile_update(platform: Literal["android", "ios"]) -> ResponseEnvelope[MobileUpdate | None]:
    prefix = f"MOBILE_{platform.upper()}"
    version = getattr(settings, f"{prefix}_LATEST_VERSION").strip()
    url = getattr(settings, f"{prefix}_UPDATE_URL").strip()
    notes = getattr(settings, f"{prefix}_RELEASE_NOTES").strip()
    if not version and not url and not notes:
        return ResponseEnvelope[MobileUpdate | None](data=None)

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        parsed = None
        hostname = None
    if (
        not VERSION_PATTERN.fullmatch(version)
        or any(character.isspace() or character == "\\" for character in url)
        or parsed is None
        or parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        logger.error("Invalid %s update configuration: version and HTTPS URL are required", platform)
        raise HTTPException(status_code=503, detail="App update information is temporarily unavailable.")
    return ResponseEnvelope[MobileUpdate | None](
        data=MobileUpdate(version=version, url=url, release_notes=notes),
    )
