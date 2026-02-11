"""Optional GUI display — one OpenCV window per camera.

All cv2.imshow / cv2.waitKey calls MUST happen on the main thread.
The StreamManager calls Display.update() and Display.tick() from the main thread.
"""

from __future__ import annotations

import cv2
import numpy as np
from loguru import logger

from argus.models import CameraConfig, MatchEvent


class Display:
    """Renders one OpenCV window per camera with detection overlays.

    Spawns N windows (one per configured camera). Each window shows the
    latest frame with bounding boxes and target names drawn on recognized faces.
    """

    def __init__(self, cameras: list[CameraConfig]) -> None:
        """Initialize display windows.

        Args:
            cameras: List of camera configurations.
        """
        self._cameras = {cam.id: cam for cam in cameras}
        self._window_names: dict[str, str] = {}

        for cam in cameras:
            window_name = f"Argus — {cam.name} [{cam.id}]"
            self._window_names[cam.id] = window_name
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window_name, 640, 480)

        logger.info("Display initialized with {} window(s)", len(cameras))

    def update(
        self,
        camera_id: str,
        frame: np.ndarray,
        detections: list[MatchEvent] | None = None,
    ) -> None:
        """Update a camera's display window with a new frame and detections.

        Args:
            camera_id: Camera identifier.
            frame: BGR numpy array to display.
            detections: Optional list of match events to draw overlays for.
        """
        window_name = self._window_names.get(camera_id)
        if window_name is None:
            return

        display_frame = frame.copy()

        # Draw detection overlays
        if detections:
            for event in detections:
                self._draw_detection(display_frame, event)

        cv2.imshow(window_name, display_frame)

    @staticmethod
    def _draw_detection(frame: np.ndarray, event: MatchEvent) -> None:
        """Draw a bounding box and label for a single detection.

        Args:
            frame: Frame to draw on (modified in-place).
            event: Match event with bbox and target info.
        """
        top, right, bottom, left = event.bbox

        # Green bounding box
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

        # Label with confidence
        label = f"{event.target_name} ({event.confidence:.0%})"
        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]

        # Label background
        cv2.rectangle(
            frame,
            (left, top - label_size[1] - 10),
            (left + label_size[0] + 4, top),
            (0, 255, 0),
            cv2.FILLED,
        )

        # Label text
        cv2.putText(
            frame,
            label,
            (left + 2, top - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            2,
        )

    @staticmethod
    def tick() -> bool:
        """Process GUI events. Must be called from the main thread.

        Returns:
            True to continue, False if the user pressed 'q' to quit.
        """
        key = cv2.waitKey(1) & 0xFF
        return key != ord("q")

    @staticmethod
    def destroy() -> None:
        """Close all display windows."""
        cv2.destroyAllWindows()
        logger.info("Display windows closed")
