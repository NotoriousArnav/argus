"""Resilient RTSP stream reader — one thread per camera."""

from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np
from loguru import logger

from argus.models import CameraConfig

# Set low-latency RTSP options globally before any VideoCapture is created.
# These apply to all FFmpeg-backed captures in this process.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp"
    "|fflags;nobuffer"
    "|flags;low_delay"
    "|analyzeduration;1000000"
    "|probesize;1000000"
    "|stimeout;5000000"
)

# Reduce default thread stack size to save memory at scale (512 KB vs 8 MB default).
# This must be called before spawning threads.
threading.stack_size(512 * 1024)


class RTSPStream:
    """Reads a single RTSP stream in a dedicated thread with automatic reconnection.

    The reader thread continuously grabs frames at full stream speed to drain the
    RTSP buffer. Consumers call `latest_frame()` to get the most recent frame at
    whatever rate they need.

    Reconnection uses exponential backoff (1s → 60s cap) to avoid hammering
    unreachable cameras.
    """

    _MAX_CONSECUTIVE_FAILURES = 30
    _BASE_RECONNECT_DELAY = 1.0
    _MAX_RECONNECT_DELAY = 60.0

    def __init__(self, camera: CameraConfig) -> None:
        self.camera = camera
        self._frame: np.ndarray | None = None
        self._has_frame = False
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._consecutive_failures = 0
        self._connected = False

        self._thread = threading.Thread(
            target=self._run,
            name=f"stream-{camera.id}",
            daemon=True,
        )
        self._thread.start()

    @property
    def is_connected(self) -> bool:
        """Whether the stream is currently connected and producing frames."""
        return self._connected

    def latest_frame(self) -> tuple[bool, np.ndarray | None]:
        """Get the most recent frame from this stream.

        Returns:
            Tuple of (success, frame). Frame is None if no frame available.
        """
        with self._lock:
            if self._has_frame and self._frame is not None:
                return True, self._frame.copy()
            return False, None

    def stop(self) -> None:
        """Signal the reader thread to stop."""
        self._stopped.set()

    def _run(self) -> None:
        """Main reader loop — connect, read frames, reconnect on failure."""
        logger.info(
            "[{}] Starting stream reader for {}", self.camera.id, self.camera.name
        )

        while not self._stopped.is_set():
            cap = self._connect()
            if cap is None:
                self._reconnect_wait()
                continue

            self._read_loop(cap)
            cap.release()

        logger.info("[{}] Stream reader stopped", self.camera.id)

    def _connect(self) -> cv2.VideoCapture | None:
        """Attempt to open the RTSP stream.

        Returns:
            VideoCapture instance if successful, None otherwise.
        """
        logger.debug("[{}] Connecting to {}", self.camera.id, self.camera.url)

        cap = cv2.VideoCapture(self.camera.url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            self._connected = True
            self._consecutive_failures = 0
            logger.info("[{}] Connected to '{}'", self.camera.id, self.camera.name)
            return cap

        logger.warning(
            "[{}] Failed to connect to '{}'",
            self.camera.id,
            self.camera.name,
        )
        cap.release()
        self._connected = False
        return None

    def _read_loop(self, cap: cv2.VideoCapture) -> None:
        """Continuously read frames until failure or stop signal."""
        failures = 0

        while not self._stopped.is_set():
            ret, frame = cap.read()

            if ret:
                with self._lock:
                    self._frame = frame
                    self._has_frame = True
                failures = 0
            else:
                failures += 1
                if failures >= self._MAX_CONSECUTIVE_FAILURES:
                    logger.warning(
                        "[{}] {} consecutive read failures — reconnecting",
                        self.camera.id,
                        failures,
                    )
                    self._connected = False
                    return  # Exit read loop to trigger reconnect

    def _reconnect_wait(self) -> None:
        """Wait with exponential backoff before attempting reconnection."""
        self._consecutive_failures += 1
        delay = min(
            self._BASE_RECONNECT_DELAY * (2 ** min(self._consecutive_failures, 6)),
            self._MAX_RECONNECT_DELAY,
        )
        logger.info(
            "[{}] Reconnecting in {:.1f}s (attempt {})",
            self.camera.id,
            delay,
            self._consecutive_failures,
        )
        # Use Event.wait() so we can be interrupted by stop()
        self._stopped.wait(timeout=delay)
