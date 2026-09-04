"""FaceNet-backed face recognition — MTCNN detector + InceptionResnetV1 encoder.

MTCNN is robust to pose and lighting; the InceptionResnetV1 FaceNet encoder
produces 512-D L2-normalized embeddings. Runs on CUDA via PyTorch. A solid
alternative to InsightFace when you want the FaceNet family on a GPU box.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import cv2
import numpy as np

from argus.detection_models import Backend, register
from argus.models import MatchEvent

_INFERENCE_LOCK = threading.Lock()


@register("facenet")
class FaceNetBackend(Backend):
    """MTCNN detection + FaceNet (InceptionResnetV1) 512-D embeddings, cosine."""

    name = "facenet"
    dim = 512
    metric = "cosine"
    _inference_lock = _INFERENCE_LOCK

    def __init__(self, settings, use_gpu: bool = False) -> None:
        super().__init__(settings, use_gpu)
        self._mtcnn = None
        self._model = None

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import facenet_pytorch  # noqa: F401
            return True
        except ImportError:
            return False

    def requires(self) -> str:
        return (
            "torch + facenet_pytorch. Install with `pip install 'argus[facenet]'`"
        )

    def build(self) -> None:
        import torch
        from facenet_pytorch import InceptionResnetV1, MTCNN

        device = torch.device("cuda" if self._use_gpu and torch.cuda.is_available() else "cpu")
        self._device = device
        self._mtcnn = MTCNN(keep_all=True, device=device)
        self._model = InceptionResnetV1(pretrained="vggface2").eval().to(device)

    def _embedding(self, tensor) -> np.ndarray:
        # tensor shape (1, 512) — L2-normalized FaceNet embedding
        vec = tensor.detach().cpu().numpy().flatten()
        return vec.astype(np.float32)

    def encode_image(self, image) -> list[np.ndarray]:
        import torch

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        with torch.no_grad():
            with _INFERENCE_LOCK:
                faces, boxes = self._mtcnn(rgb, return_prob=False)
                if faces is None:
                    return []
                embeds = self._model(faces)
        return [self._embedding(e) for e in embeds]

    def distance(self, gallery: np.ndarray, encoding: np.ndarray) -> np.ndarray:
        cos_sim = gallery @ encoding
        return np.clip(1.0 - cos_sim, 0.0, 1.0)

    def detect(
        self,
        frame: np.ndarray,
        camera_id: str,
        camera_name: str,
    ) -> list[MatchEvent]:
        import torch

        scale = self._settings.frame_scale
        small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        with torch.no_grad():
            with _INFERENCE_LOCK:
                faces, boxes = self._mtcnn(rgb_small, return_prob=False)
                if faces is None:
                    return []
                embeds = self._model(faces)
        encodings = [self._embedding(e) for e in embeds]

        locations = []
        if boxes is not None:
            for x1, y1, x2, y2 in boxes.tolist():
                locations.append((int(y1), int(x2), int(y2), int(x1)))

        now = datetime.now(timezone.utc)
        return self._match(
            encodings, locations, scale, frame, camera_id, camera_name, now
        )
