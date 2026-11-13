import io
import logging
from math import hypot, isfinite
from uuid import UUID

import face_recognition
import numpy as np

DEFAULT_MATCH_THRESHOLD = 0.5
DEFAULT_MATCH_MARGIN = 0.05
DEFAULT_ENROLLMENT_CONFLICT_THRESHOLD = 0.4

logger = logging.getLogger(__name__)


def match_threshold() -> float:
    from app.core.config import settings

    return float(getattr(settings, "FACE_MATCH_THRESHOLD", DEFAULT_MATCH_THRESHOLD))


def match_margin() -> float:
    from app.core.config import settings

    return float(getattr(settings, "FACE_MATCH_MARGIN", DEFAULT_MATCH_MARGIN))


def enrollment_conflict_threshold() -> float:
    """Distance at or below which an enrollment capture is flagged as a possible duplicate identity.

    This governs only the enrollment conflict check; attendance acceptance uses match_threshold().
    """
    from app.core.config import settings

    return float(getattr(
        settings, "FACE_ENROLLMENT_CONFLICT_THRESHOLD", DEFAULT_ENROLLMENT_CONFLICT_THRESHOLD,
    ))


def face_encoding_norm(encoding: list[float], *, source: str = "Captured face") -> float:
    message = (
        f"{source} encoding is invalid: expected 128 finite numbers with a finite, non-zero norm."
    )
    try:
        vector = np.asarray(encoding, dtype=float)
    except (TypeError, ValueError, OverflowError) as error:
        logger.warning("FACE_ENCODING_INVALID source=%s reason=non_numeric", source)
        raise ValueError(message) from error
    if vector.shape != (128,) or not np.isfinite(vector).all():
        logger.warning("FACE_ENCODING_INVALID source=%s reason=shape_or_non_finite shape=%s", source, vector.shape)
        raise ValueError(message)
    norm = hypot(*vector)
    if not isfinite(norm) or norm == 0:
        logger.warning("FACE_ENCODING_INVALID source=%s reason=invalid_norm norm=%r", source, norm)
        raise ValueError(message)
    return norm


def face_distances(candidate_encoding: list[float], known_encodings: list[list[float]]) -> list[float]:
    face_encoding_norm(candidate_encoding)
    if not known_encodings:
        return []
    for vector in known_encodings:
        face_encoding_norm(vector, source="Stored face")
    vectors = [np.asarray(vector, dtype=float) for vector in known_encodings]
    return [float(d) for d in face_recognition.face_distance(vectors, np.asarray(candidate_encoding, dtype=float))]


def extract_face_encoding(image_bytes: bytes) -> list[float]:
    """Runs face detection + 128-d embedding extraction on an uploaded image."""
    image = face_recognition.load_image_file(io.BytesIO(image_bytes))
    encodings = face_recognition.face_encodings(image)

    if not encodings:
        raise ValueError("No face detected in the provided image.")
    if len(encodings) > 1:
        raise ValueError("Multiple faces detected; please provide an image with a single face.")

    encoding = encodings[0].tolist()
    face_encoding_norm(encoding)
    return encoding


def find_best_match(
    candidate_encoding: list[float],
    known_encodings: list[tuple[UUID, list[float]]],
    threshold: float | None = None,
    margin: float | None = None,
) -> tuple[UUID, float] | None:
    """1:N face search. known_encodings is a list of (employee_id, encoding) pairs.

    Returns the (employee_id, distance) of the closest match within the threshold, or None when there is
    no match or when another employee is nearly as close (the identity would be ambiguous).
    """
    if not known_encodings:
        return None

    limit = match_threshold() if threshold is None else threshold
    required_margin = match_margin() if margin is None else margin
    user_ids, vectors = zip(*known_encodings)
    distances = face_distances(candidate_encoding, list(vectors))

    nearest: dict[UUID, float] = {}
    for employee_id, distance in zip(user_ids, distances):
        nearest[employee_id] = min(distance, nearest.get(employee_id, distance))
    ranked = sorted(nearest.items(), key=lambda item: item[1])
    best_id, best_distance = ranked[0]

    if best_distance > limit:
        return None
    # Similar-looking employees can both be enrolled (HR override), so never pick between near ties.
    if len(ranked) > 1 and ranked[1][1] - best_distance < required_margin:
        logger.info(
            "Face match rejected as ambiguous: best %.4f, runner-up %.4f, margin %.4f.",
            best_distance, ranked[1][1], required_margin,
        )
        return None

    return best_id, float(best_distance)
