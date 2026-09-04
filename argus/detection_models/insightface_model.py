"""InsightFace-backed face recognition — state-of-the-art on beefy hardware.

Uses the ``buffalo_l`` pack: an SCRFD face detector (handles tiny, blurred,
and occluded faces) and an ArcFace / ResNet100 encoder producing 512-D
embeddings. Runs on CUDA via onnxruntime-gpu. This is the high-accuracy tier
for a serious machine.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import cv2
import numpy as np

from argus.detection_models import Backend, register
from argus.models import MatchEvent

_INFERENCE_LOCK = threading.Lock()


@register("insightface")
class InsightFaceBackend(Backend):
    """SCRFD detection + ArcFace / ResNet100 512-D embeddings, cosine matching."""

    name = "insightface"
    dim = 512
    metric = "cosine"
    _inference_lock = _INFERENCE_LOCK

    def __init__(self, settings, use_gpu: bool = False) -> None:
        super().__init__(settings, use_gpu)
        self._app = None

    def is_available(self) -> bool:
        try:
            import insightface  # noqa: F401
            return True
        except ImportError:
            return False

    def requires(self) -> str:
        return (
            "insightface + onnxruntime (-gpu for CUDA). "
            "Install with `pip install 'argus[gpu]'`"
        )

    def build(self) -> None:
        import insightface
        from insightface.app import FaceAnalysis

        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if self._use_gpu
            else ["CPUExecutionProvider"]
        )
        self._app = FaceAnalysis(
            name="buffalo_l",
            providers=providers,
            allowed_modules=["detection", "recognition"],
        )
        self._app.prepare(ctx_id=0 if self._use_gpu else -1, det_size=(640, 640))

    @staticmethod
    def _faces_from_app(app, rgb) -> list:
        """Run detection + recognition, returning detected Face objects.

        Each Face carries ``.bbox`` (4 float coords), ``.embedding`` (512-D
        normalized vector), and ``.det_score``.
        """
        return app.get(rgb)

    def _embedding(self, face) -> np.ndarray:
        return np.asarray(face.embedding, dtype=np.float32)

    def encode_image(self, image) -> list[np.ndarray]:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        with _INFERENCE_LOCK:
            faces = self._faces_from_app(self._app, rgb)
        return [self._embedding(f) for f in faces]

    def distance(self, gallery: np.ndarray, encoding: np.ndarray) -> np.ndarray:
        # cosine distance = 1 - cosine_similarity, clamped to [0, 1]
        cos_sim = gallery @ encoding  # rows are normalized embeddings
        return np.clip(1.0 - cos_sim, 0.0, 1.0)

    def detect(
        self,
        frame: np.ndarray,
        camera_id: str,
        camera_name: str,
    ) -> list[MatchEvent]:
        scale = self._settings.frame_scale
        small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        with _INFERENCE_LOCK:
            faces = self._faces_from_app(self._app, rgb_small)
            if not faces:
                return []
            encodings = [self._embedding(f) for f in faces]

        locations = []
        for f in faces:
            # SCRFD returns bbox as (x1, y1, x2, y2) in downscaled coords.
            x1, y1, x2, y2 = f.bbox.astype(int)
            locations.append((y1, x2, y2, x1))  # -> (top, right, bottom, left)

        now = datetime.now(timezone.utc)
        return self._match(
            encodings, locations, scale, frame, camera_id, camera_name, now
        )
