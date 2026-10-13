import asyncio
import json
import logging
import re
import time
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

router = APIRouter(prefix="/psgc", tags=["Philippine Geographic Codes"])
logger = logging.getLogger(__name__)
_BASE_URL = "https://psgc.gitlab.io/api"
_CACHE_TTL_SECONDS = 60 * 60
_cache: dict[str, tuple[float, list["PSGCPlace"]]] = {}
_cache_lock = Lock()
_CODE_PATTERN = re.compile(r"^\d{9}$")


class PSGCPlace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(pattern=r"^\d{9}$")
    name: str = Field(min_length=1)


def _fetch_places(path: str) -> list[PSGCPlace]:
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(path)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    request = Request(
        f"{_BASE_URL}/{path}",
        headers={"Accept": "application/json", "User-Agent": "MagnusTimekeeping/1.0"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
        if not isinstance(payload, list):
            raise ValueError("PSGC API returned a non-list response.")
        places = [PSGCPlace.model_validate(item) for item in payload]
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError, ValidationError) as error:
        logger.exception("Could not retrieve PSGC reference data from %s.", path)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Philippine geographic reference data is temporarily unavailable.",
        ) from error

    with _cache_lock:
        _cache[path] = (time.monotonic(), places)
    return places


async def _get_places(path: str) -> list[PSGCPlace]:
    return await asyncio.to_thread(_fetch_places, path)


def _validate_code(code: str) -> str:
    if not _CODE_PATTERN.fullmatch(code):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PSGC code must contain exactly 9 digits.",
        )
    return code


@router.get("/regions", response_model=list[PSGCPlace])
async def list_regions() -> list[PSGCPlace]:
    return await _get_places("regions/")


@router.get("/regions/{region_code}/provinces", response_model=list[PSGCPlace])
async def list_provinces(
    region_code: str = Path(..., min_length=9, max_length=9),
) -> list[PSGCPlace]:
    return await _get_places(f"regions/{_validate_code(region_code)}/provinces/")


@router.get(
    "/provinces/{province_code}/cities-municipalities",
    response_model=list[PSGCPlace],
)
async def list_province_cities(
    province_code: str = Path(..., min_length=9, max_length=9),
) -> list[PSGCPlace]:
    return await _get_places(
        f"provinces/{_validate_code(province_code)}/cities-municipalities/"
    )


@router.get(
    "/regions/{region_code}/cities-municipalities",
    response_model=list[PSGCPlace],
)
async def list_region_cities(
    region_code: str = Path(..., min_length=9, max_length=9),
) -> list[PSGCPlace]:
    return await _get_places(
        f"regions/{_validate_code(region_code)}/cities-municipalities/"
    )


@router.get(
    "/cities-municipalities/{city_code}/barangays",
    response_model=list[PSGCPlace],
)
async def list_barangays(
    city_code: str = Path(..., min_length=9, max_length=9),
) -> list[PSGCPlace]:
    return await _get_places(
        f"cities-municipalities/{_validate_code(city_code)}/barangays/"
    )
