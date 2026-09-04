"""dlib-based face recognition backend — the lightweight, battle-tested default.

Wraps the `face_recognition` library (dlib HOG or CNN detector + 128-D ResNet
encodings). This is the original Argus behavior, preserved verbatim so the
default path is a strict no-regression.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import cv2
import numpy as np

from argus.detection_models import Backend, register
from argus.models import MatchEvent

# Module-level lock for all face_recognition calls.
# The library uses global dlib singletons that are not thread-safe.
_DETECTION_LOCK = threading.Lock()


class DlibBackend(Backend):
    """128-D dlib encodings, euclidean matching. Shared HOG/CNN logic."""

    name = "dlib"
    dim = 128
    metric = "euclidean"
    _model = "hog"
    _inference_lock = _DETECTION_LOCK

    def is_available(self) -> bool:
        try:
            import face_recognition  # noqa: F401
            return True
        except ImportError:
            return False

    def requires(self) -> str:
        return "dlib / face_recognition (face-recognition + face-recognition-models)"

    def build(self) -> None:
        # dlib lazily loads its detector/encoder on first call; nothing to
        # preload here.
        pass

    def encode_image(self, image) -> list[np.ndarray]:
        import face_recognition
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return face_recognition.face_encodings(rgb, num_jitters=1)

    def distance(self, gallery: np.ndarray, encoding: np.ndarray) -> np.ndarray:
        import face_recognition
        return face_recognition.face_distance(gallery, encoding)

    def detect(
        self,
        frame: np.ndarray,
        camera_id: str,
        camera_name: str,
    ) -> list[MatchEvent]:
        import face_recognition

        scale = self._settings.frame_scale
        small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        # All face_recognition calls under the lock (dlib not thread-safe).
        with _DETECTION_LOCK:
            locations = face_recognition.face_locations(rgb_small, model=self._model)
            if not locations:
                return []
            encodings = face_recognition.face_encodings(rgb_small, locations)

        now = datetime.now(timezone.utc)
        return self._match(
            encodings, locations, scale, frame, camera_id, camera_name, now
        )


@register("dlib_hog")
class DlibHogBackend(DlibBackend):
    """HOG face detector + 128-D dlib encodings, euclidean matching.

    The original Argus behavior. CPU-only, light, runs anywhere Python does
    — including a Raspberry Pi — and scales fine on beefier hardware.
    """

    name = "dlib_hog"
    _model = "hog"


@register("dlib_cnn")
class DlibCnnBackend(DlibBackend):
    """Same 128-D dlib encodings but with the CNN face detector.

    The CNN detector handles small, blurred, and angled faces far better than
    HOG, but needs a GPU or many CPU cores. Identical embeddings/metric to
    ``dlib_hog``, so the same target gallery works for both.
    """

    name = "dlib_cnn"
    _model = "cnn"
