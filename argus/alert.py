"""Alert handler — log, screenshot, and webhook notifications on face match."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import cv2
import httpx
from loguru import logger

from argus.models import MatchEvent, Settings, WebhookConfig


class AlertHandler:
    """Handles face match events: structured logging, screenshots, and webhooks.

    Enforces a per-(target, camera) cooldown to avoid alert spam.
    Webhook calls are fire-and-forget in daemon threads to never block detection.
    """

    def __init__(
        self,
        settings: Settings,
        webhooks: list[WebhookConfig],
    ) -> None:
        self._settings = settings
        self._webhooks = webhooks
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._cooldown_lock = threading.Lock()

        # Ensure output directories exist
        self._screenshot_dir = Path(settings.screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        log_dir = Path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Configure loguru sinks
        self._setup_logging(log_dir)

    def _setup_logging(self, log_dir: Path) -> None:
        """Configure loguru with console and structured JSON file sinks."""
        # Remove default sink to avoid duplicate console output
        logger.remove()

        # Console: human-readable, colored
        logger.add(
            sys.stderr,
            level="INFO",
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level:<8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
                "{message}"
            ),
        )

        # Structured JSON file: machine-parseable, rotated daily
        logger.add(
            str(log_dir / "detections.json"),
            serialize=True,
            rotation="00:00",
            retention="30 days",
            compression="zip",
            level="INFO",
        )

    def handle(self, event: MatchEvent) -> None:
        """Process a face match event.

        Checks cooldown, then logs, saves screenshot, and fires webhooks.

        Args:
            event: The face match event to handle.
        """
        if self._is_on_cooldown(event.target_name, event.camera_id):
            return

        self._update_cooldown(event.target_name, event.camera_id)

        # 1. Structured log
        screenshot_path = self._save_screenshot(event)

        # 2. Log the match
        match_log = logger.bind(
            person=event.target_name,
            camera=event.camera_name,
            camera_id=event.camera_id,
            confidence=event.confidence,
            screenshot=str(screenshot_path),
        )
        match_log.success(
            "MATCH: '{}' on '{}' (confidence: {:.1%})",
            event.target_name,
            event.camera_name,
            event.confidence,
        )

        # 3. Fire webhooks (non-blocking)
        if self._webhooks:
            self._fire_webhooks(event, str(screenshot_path))

    def _is_on_cooldown(self, target_name: str, camera_id: str) -> bool:
        """Check if the (target, camera) pair is within the cooldown window."""
        key = (target_name, camera_id)
        with self._cooldown_lock:
            last_alert = self._cooldowns.get(key, 0.0)
            return (time.monotonic() - last_alert) < self._settings.cooldown

    def _update_cooldown(self, target_name: str, camera_id: str) -> None:
        """Record the current time as the last alert for this (target, camera) pair."""
        key = (target_name, camera_id)
        with self._cooldown_lock:
            self._cooldowns[key] = time.monotonic()

    def _save_screenshot(self, event: MatchEvent) -> Path:
        """Save an annotated screenshot of the match.

        Args:
            event: The match event containing the frame and bbox.

        Returns:
            Path to the saved screenshot file.
        """
        timestamp_str = event.timestamp.strftime("%Y-%m-%d_%H-%M-%S_%f")
        filename = f"{timestamp_str}_{event.camera_id}_{event.target_name}.jpg"
        filepath = self._screenshot_dir / filename

        if event.frame is not None:
            annotated = event.frame.copy()
            top, right, bottom, left = event.bbox

            # Draw bounding box
            cv2.rectangle(annotated, (left, top), (right, bottom), (0, 255, 0), 2)

            # Draw label background
            label = f"{event.target_name} ({event.confidence:.0%})"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
            cv2.rectangle(
                annotated,
                (left, top - label_size[1] - 10),
                (left + label_size[0] + 4, top),
                (0, 255, 0),
                cv2.FILLED,
            )
            cv2.putText(
                annotated,
                label,
                (left + 2, top - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 0),
                2,
            )

            cv2.imwrite(str(filepath), annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        else:
            logger.warning("No frame data for screenshot: {}", filename)

        return filepath

    def _fire_webhooks(self, event: MatchEvent, screenshot_path: str) -> None:
        """Send webhook notifications in background threads (fire-and-forget).

        Args:
            event: The match event.
            screenshot_path: Path to the saved screenshot.
        """
        for webhook in self._webhooks:
            thread = threading.Thread(
                target=self._send_webhook,
                args=(webhook, event, screenshot_path),
                daemon=True,
            )
            thread.start()

    @staticmethod
    def _send_webhook(
        webhook: WebhookConfig,
        event: MatchEvent,
        screenshot_path: str,
    ) -> None:
        """Send a single webhook notification.

        Args:
            webhook: Webhook configuration.
            event: The match event.
            screenshot_path: Path to the saved screenshot.
        """
        import json
        import re

        # Build the replacement map
        replacements = {
            "name": event.target_name,
            "camera": event.camera_name,
            "camera_id": event.camera_id,
            "confidence": event.confidence,
            "timestamp": event.timestamp.isoformat(),
            "screenshot": screenshot_path,
        }

        try:
            # Use regex substitution instead of str.format() to avoid
            # conflicts with JSON curly braces. Matches {placeholder} patterns.
            def _replace(match: re.Match) -> str:
                key = match.group(1)
                if key not in replacements:
                    raise KeyError(key)
                value = replacements[key]
                # Numbers should not be quoted in JSON
                if isinstance(value, (int, float)):
                    return str(value)
                return str(value)

            body = re.sub(r"\{(\w+)\}", _replace, webhook.body_template)
        except KeyError as e:
            logger.error(
                "Webhook '{}' body_template error: unknown placeholder {}",
                webhook.id,
                e,
            )
            return

        headers = {"Content-Type": "application/json", **webhook.headers}

        try:
            resp = httpx.request(
                method=webhook.method,
                url=webhook.url,
                content=body,
                headers=headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.debug(
                "Webhook '{}' sent successfully ({})", webhook.id, resp.status_code
            )
        except httpx.TimeoutException:
            logger.warning("Webhook '{}' timed out", webhook.id)
        except httpx.HTTPStatusError as e:
            logger.error(
                "Webhook '{}' HTTP error: {}", webhook.id, e.response.status_code
            )
        except httpx.RequestError as e:
            logger.error("Webhook '{}' request error: {}", webhook.id, e)
