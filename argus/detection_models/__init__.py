"""Pluggable face recognition backends for Argus.

Each backend is self-contained: it knows how to detect faces and compute
encodings for a specific model family. Argus stays model-agnostic — the
detector resolves which backend to use from configuration and exposes it
through the uniform :class:`Backend` contract.

Backends differ in detector, encoder, embedding dimension, and similarity
metric, but every one presents the same surface to the rest of the pipeline:

- ``name`` — config-identifiable string (e.g. ``"dlib_hog"``)
- ``dim`` — embedding dimension (128 for dlib, 512 for ArcFace/FaceNet)
- ``metric`` — similarity metric (``"euclidean"`` or ``"cosine"``)
- ``detect(frame, camera_id, camera_name)`` — full pipeline -> MatchEvents
- ``is_available()`` — whether the backend's dependencies are installed

The dispatcher builds a backend, attaches the target gallery with
:meth:`Backend.set_gallery`, then hands it to the pipeline. Detection and
encoding are always serialized behind a lock because dlib / GPU runtimes
use global objects that are not thread-safe.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

import numpy as np

from argus.models import MatchEvent, Settings


class Backend(ABC):
    """Uniform contract every face recognition backend must implement."""

    #: Config-identifiable name (matches the ``model_backend`` setting).
    name: str = ""

    #: Embedding dimension produced by the encoder (128 or 512).
    dim: int = 128

    #: Similarity metric for matching ("euclidean" or "cosine").
    metric: str = "euclidean"

    #: Module-level lock serializing all inference (dlib / CUDA not thread-safe).
    _inference_lock = None

    def __init__(self, settings: Settings, use_gpu: bool = False) -> None:
        self._settings = settings
        self._use_gpu = use_gpu
        self._gallery: np.ndarray | None = None
        self._gallery_names: list[str] = []

    # ---- availability -----------------------------------------------------

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend's runtime dependencies are installed."""

    def requires(self) -> str:
        """Human-readable dependency description (shown on missing deps)."""
        return self.name

    # ---- setup ------------------------------------------------------------

    @abstractmethod
    def build(self) -> None:
        """Load pre-trained models. Called once at startup after availability check."""

    def set_gallery(
        self, gallery: np.ndarray | None, names: list[str]
    ) -> None:
        """Attach the target encoding gallery and parallel name list."""
        self._gallery = gallery
        self._gallery_names = list(names)

    @property
    def has_targets(self) -> bool:
        return self._gallery is not None and len(self._gallery) > 0

    @property
    def gallery_size(self) -> int:
        return len(self._gallery_names)

    # ---- target encoding --------------------------------------------------

    @abstractmethod
    def encode_image(self, image) -> list[np.ndarray]:
        """Compute embeddings for a target reference image (num_jitters applied)."""

    def ndarray_from_file(self, path: str) -> np.ndarray:
        """Load an image file into a BGR numpy array (OpenCV capture order).

        Target images are loaded via the same code path so every backend
        consumes identical arrays. Raises on unreadable files.
        """
        import cv2
        img = cv2.imread(path)
        if img is None:
            raise ValueError(f"Could not read image file: {path}")
        return img

    # ---- live detection ---------------------------------------------------

    @abstractmethod
    def detect(
        self,
        frame: np.ndarray,
        camera_id: str,
        camera_name: str,
    ) -> list[MatchEvent]:
        """Run detection + recognition on a frame, returning MatchEvents."""

    # ---- shared matching helper -------------------------------------------

    def distance(self, gallery: np.ndarray, encoding: np.ndarray) -> np.ndarray:
        """Compute the similarity distances between one encoding and the gallery.

        Returns a 1-D array, one entry per gallery row. For euclidean backends
        this is L2 distance; for cosine backends it is cosine distance clamped
        to [0, 1]. Lower is a better match in both cases.
        """
        raise NotImplementedError

    def confidence_from_distance(self, distance: float) -> float:
        """Map a distance to a confidence score in (0, 1]. Higher = better."""
        return round(1.0 - float(distance), 3)

    def _match(
        self,
        encodings: list[np.ndarray],
        locations: list,
        scale: float,
        frame: np.ndarray,
        camera_id: str,
        camera_name: str,
        now,
    ) -> list[MatchEvent]:
        """Match detected encodings against the gallery and build MatchEvents.

        Shared by all backends. ``locations`` are in *downscaled* coordinates
        (top, right, bottom, left) and are scaled back to original frame size
        here. Encodings and locations are zipped positionally.
        """
        if not self.has_targets or not encodings:
            return []

        inv_scale = 1.0 / scale
        matches: list[MatchEvent] = []
        tolerance = self._settings.tolerance

        for encoding, (top, right, bottom, left) in zip(encodings, locations):
            distances = self.distance(self._gallery, encoding)
            best_idx = int(np.argmin(distances))
            best_distance = float(distances[best_idx])

            if best_distance <= tolerance:
                matches.append(
                    MatchEvent(
                        target_name=self._gallery_names[best_idx],
                        camera_id=camera_id,
                        camera_name=camera_name,
                        confidence=self.confidence_from_distance(best_distance),
                        timestamp=now,
                        bbox=(
                            int(top * inv_scale),
                            int(right * inv_scale),
                            int(bottom * inv_scale),
                            int(left * inv_scale),
                        ),
                        frame=frame,
                    )
                )

        return matches


# Registry: config name -> backend factory callable.
_REGISTRY: dict[str, type[Backend]] = {}


def register(name: str) -> Callable[[type[Backend]], type[Backend]]:
    """Decorator to register a backend class under ``name``."""
    def decorator(cls: type[Backend]) -> type[Backend]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return decorator


def available_backends() -> list[str]:
    """Return the sorted list of registered backend config names."""
    return sorted(_REGISTRY)


def get_backend(name: str, settings: Settings, use_gpu: bool = False) -> Backend:
    """Resolve a backend by config name, raising a clear error if unavailable.

    Args:
        name: The ``model_backend`` config value.
        settings: Global settings (tolerance, frame_scale, ...).
        use_gpu: Whether to attempt GPU acceleration.

    Returns:
        A constructed (gallery-less) :class:`Backend` instance.

    Raises:
        ValueError: If ``name`` is not registered, or its dependencies are
            missing.
    """
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown model_backend '{name}'. Available: {available_backends()}"
        )

    backend = _REGISTRY[name](settings=settings, use_gpu=use_gpu)

    if not backend.is_available():
        raise ValueError(
            f"model_backend '{name}' selected but its dependencies are not "
            f"installed ({backend.requires()}). Install with "
            f"`pip install 'argus[{name}]'` or switch back to 'dlib_hog'."
        )

    backend.build()
    return backend
