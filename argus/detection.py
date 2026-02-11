"""Face detection and recognition against known targets."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import cv2
import face_recognition
import numpy as np
from loguru import logger

from argus.models import MatchEvent, Settings

# Module-level lock for all face_recognition calls.
# The library uses global dlib singletons that are not thread-safe.
_DETECTION_LOCK = threading.Lock()


class FaceDetector:
    """Detects faces in frames and matches them against known target encodings.

    All face_recognition calls are serialized behind a lock because dlib's
    global detector/encoder objects are not thread-safe.
    """

    def __init__(
        self,
        all_encodings: np.ndarray | None,
        encoding_names: list[str],
        settings: Settings,
    ) -> None:
        """Initialize the detector.

        Args:
            all_encodings: (N, 128) array of all target face encodings, or None.
            encoding_names: List of target names, one per encoding row.
            settings: Global settings (tolerance, frame_scale).
        """
        self._all_encodings = all_encodings
        self._encoding_names = encoding_names
        self._tolerance = settings.tolerance
        self._frame_scale = settings.frame_scale
        self._has_targets = all_encodings is not None and len(all_encodings) > 0

        if not self._has_targets:
            logger.warning(
                "No target encodings loaded — detection will find faces but not identify them"
            )

    def detect(
        self,
        frame: np.ndarray,
        camera_id: str,
        camera_name: str,
    ) -> list[MatchEvent]:
        """Run face detection and recognition on a single frame.

        Args:
            frame: BGR numpy array from OpenCV (full resolution).
            camera_id: Camera identifier.
            camera_name: Human-readable camera name.

        Returns:
            List of MatchEvent for each recognized face.
        """
        # Downscale for faster detection
        scale = self._frame_scale
        small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        # All face_recognition calls under the lock
        with _DETECTION_LOCK:
            face_locations = face_recognition.face_locations(rgb_small, model="hog")

            if not face_locations:
                return []

            face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

        if not self._has_targets or not face_encodings:
            return []

        # Match each detected face against known targets
        now = datetime.now(timezone.utc)
        matches: list[MatchEvent] = []
        inv_scale = 1.0 / scale

        for encoding, (top, right, bottom, left) in zip(face_encodings, face_locations):
            distances = face_recognition.face_distance(self._all_encodings, encoding)
            best_idx = np.argmin(distances)
            best_distance = distances[best_idx]

            if best_distance <= self._tolerance:
                # Scale bbox back to original frame coordinates
                orig_top = int(top * inv_scale)
                orig_right = int(right * inv_scale)
                orig_bottom = int(bottom * inv_scale)
                orig_left = int(left * inv_scale)

                matches.append(
                    MatchEvent(
                        target_name=self._encoding_names[best_idx],
                        camera_id=camera_id,
                        camera_name=camera_name,
                        confidence=round(1.0 - best_distance, 3),
                        timestamp=now,
                        bbox=(orig_top, orig_right, orig_bottom, orig_left),
                        frame=frame,
                    )
                )

        return matches
