"""Stream manager — orchestrates all camera streams, detection, and alerting."""

from __future__ import annotations

import signal
import time

from loguru import logger

from argus.alert import AlertHandler
from argus.detection import FaceDetector
from argus.display import Display
from argus.models import CameraConfig, Settings
from argus.stream import RTSPStream


class StreamManager:
    """Orchestrates the full Argus pipeline.

    - Spawns one RTSPStream thread per camera.
    - Runs the main processing loop on the calling thread (must be main thread if GUI).
    - For each camera, grabs the latest frame at `detection_interval` rate.
    - Runs face detection/recognition and dispatches matches to the alert handler.
    - Optionally updates the GUI display.
    """

    def __init__(
        self,
        settings: Settings,
        cameras: list[CameraConfig],
        detector: FaceDetector,
        alert_handler: AlertHandler,
        display: Display | None = None,
    ) -> None:
        self._settings = settings
        self._cameras = cameras
        self._detector = detector
        self._alert_handler = alert_handler
        self._display = display
        self._streams: dict[str, RTSPStream] = {}
        self._last_detection_time: dict[str, float] = {}
        self._running = False

    def start(self) -> None:
        """Start all streams and enter the main processing loop.

        This method blocks until interrupted (Ctrl+C or 'q' in GUI).
        Must be called from the main thread if GUI is enabled.
        """
        self._running = True

        # Register signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Spawn one RTSPStream per camera
        logger.info("Starting {} camera stream(s)...", len(self._cameras))
        for camera in self._cameras:
            self._streams[camera.id] = RTSPStream(camera)
            self._last_detection_time[camera.id] = 0.0

        logger.info("Argus is watching. Press Ctrl+C to stop.")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _main_loop(self) -> None:
        """Main processing loop — iterate cameras, detect faces, handle alerts."""
        interval = self._settings.detection_interval

        while self._running:
            now = time.monotonic()

            for camera in self._cameras:
                if not self._running:
                    break

                stream = self._streams.get(camera.id)
                if stream is None:
                    continue

                # Time-gate detection per camera
                elapsed = now - self._last_detection_time[camera.id]
                if elapsed < interval:
                    continue

                # Grab latest frame
                ok, frame = stream.latest_frame()
                if not ok or frame is None:
                    continue

                self._last_detection_time[camera.id] = now

                # Run face detection + recognition
                matches = self._detector.detect(frame, camera.id, camera.name)

                # Handle any matches
                for event in matches:
                    self._alert_handler.handle(event)

                # Update GUI if enabled
                if self._display is not None:
                    self._display.update(camera.id, frame, matches if matches else None)

            # GUI tick (must happen on main thread)
            if self._display is not None:
                if not self._display.tick():
                    logger.info("Quit signal from GUI")
                    self._running = False
                    break

            # Brief sleep to avoid busy-waiting — 10ms is enough to stay responsive
            time.sleep(0.01)

    def _signal_handler(self, signum: int, _frame: object) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info("Received signal {}, shutting down...", signum)
        self._running = False

    def _shutdown(self) -> None:
        """Stop all streams and clean up resources."""
        logger.info("Shutting down Argus...")

        for cam_id, stream in self._streams.items():
            logger.debug("Stopping stream '{}'", cam_id)
            stream.stop()

        if self._display is not None:
            self._display.destroy()

        logger.info("Argus stopped. All-seeing eyes closed.")
