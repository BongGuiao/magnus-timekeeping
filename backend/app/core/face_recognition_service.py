import io
from uuid import UUID

import face_recognition
import numpy as np

DEFAULT_MATCH_THRESHOLD = 0.5


def match_threshold() -> float:
    from app.core.config import settings

    return float(getattr(settings, "FACE_MATCH_THRESHOLD", DEFAULT_MATCH_THRESHOLD))


def face_distances(candidate_encoding: list[float], known_encodings: list[list[float]]) -> list[float]:
    if not known_encodings:
        return []
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

    return encodings[0].tolist()


def find_best_match(
    candidate_encoding: list[float],
    known_encodings: list[tuple[UUID, list[float]]],
    threshold: float | None = None,
) -> tuple[UUID, float] | None:
    """1:N face search. known_encodings is a list of (employee_id, encoding) pairs.

    Returns the (employee_id, distance) of the closest match within the threshold, or None if no match.
    """
    if not known_encodings:
        return None

    limit = match_threshold() if threshold is None else threshold
    user_ids, vectors = zip(*known_encodings)
    distances = face_distances(candidate_encoding, list(vectors))

    best_index = int(np.argmin(distances))
    best_distance = float(distances[best_index])

    if best_distance > limit:
        return None

    return user_ids[best_index], best_distance
