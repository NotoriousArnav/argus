"""Data models for Argus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass
class CameraConfig:
    """Configuration for a single RTSP camera."""

    id: str
    name: str
    url: str


@dataclass
class Settings:
    """Global detection and runtime settings."""

    detection_interval: float = 0.5
    tolerance: float = 0.6
    frame_scale: float = 0.25
    screenshot_dir: str = "screenshots"
    log_dir: str = "logs"
    cooldown: int = 10
    model_backend: str = "dlib_hog"
    use_gpu: bool = False

    _VALID_BACKENDS = frozenset(
        {"dlib_hog", "dlib_cnn", "insightface", "facenet"}
    )

    def __post_init__(self) -> None:
        if not 0.0 < self.frame_scale <= 1.0:
            raise ValueError(f"frame_scale must be in (0, 1], got {self.frame_scale}")
        if not 0.0 < self.tolerance <= 1.0:
            raise ValueError(f"tolerance must be in (0, 1], got {self.tolerance}")
        if self.detection_interval <= 0:
            raise ValueError(
                f"detection_interval must be > 0, got {self.detection_interval}"
            )
        if self.model_backend not in self._VALID_BACKENDS:
            raise ValueError(
                f"model_backend must be one of {sorted(self._VALID_BACKENDS)}, "
                f"got {self.model_backend}"
            )


@dataclass
class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    id: str
    enabled: bool = True
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body_template: str = ""


@dataclass
class Target:
    """A surveillance target with pre-computed face encodings."""

    name: str
    encodings: list[np.ndarray] = field(default_factory=list)


@dataclass
class MatchEvent:
    """A face recognition match event."""

    target_name: str
    camera_id: str
    camera_name: str
    confidence: float
    timestamp: datetime
    bbox: tuple[int, int, int, int]  # (top, right, bottom, left) in original coords
    frame: np.ndarray | None = field(default=None, repr=False)
