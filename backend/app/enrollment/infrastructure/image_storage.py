from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageOps

MAX_REFERENCE_IMAGE_EDGE = 640
MAX_SOURCE_IMAGE_PIXELS = 20_000_000


def face_image_directory() -> Path:
    return Path(__file__).resolve().parents[4] / "static" / "employee-faces"


def face_image_path(image_id: UUID) -> Path:
    return face_image_directory() / f"{image_id}.jpg"


def face_image_reference(image_id: UUID) -> str:
    return f"/enrollment/photos/{image_id}.jpg"


def face_reference_path(reference: str | None) -> Path | None:
    if not reference or not reference.startswith("/enrollment/photos/") or not reference.endswith(".jpg"):
        return None
    try:
        image_id = UUID(reference.removeprefix("/enrollment/photos/")[:-4])
    except ValueError:
        return None
    if face_image_reference(image_id) != reference:
        return None
    return face_image_path(image_id)


def prepare_face_reference_image(image_bytes: bytes) -> bytes:
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            if source.width * source.height > MAX_SOURCE_IMAGE_PIXELS:
                raise ValueError("Face image dimensions are too large.")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError("Face image is not a valid supported image.") from error

    image.thumbnail(
        (MAX_REFERENCE_IMAGE_EDGE, MAX_REFERENCE_IMAGE_EDGE),
        Image.Resampling.LANCZOS,
    )
    output = BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()
