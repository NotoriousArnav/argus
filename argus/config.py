"""Configuration loading and validation for Argus."""

from __future__ import annotations

import tomllib
from pathlib import Path

from loguru import logger

from argus.models import CameraConfig, Settings, WebhookConfig

DEFAULT_CONFIG_DIR = Path("config")


def load_cameras_config(
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> tuple[Settings, list[CameraConfig]]:
    """Load cameras.toml and return settings + camera list.

    Args:
        config_dir: Path to the configuration directory.

    Returns:
        Tuple of (Settings, list of CameraConfig).

    Raises:
        FileNotFoundError: If cameras.toml does not exist.
        ValueError: If configuration is invalid.
    """
    cameras_path = config_dir / "cameras.toml"
    if not cameras_path.exists():
        raise FileNotFoundError(f"Camera config not found: {cameras_path}")

    with open(cameras_path, "rb") as f:
        raw = tomllib.load(f)

    # Parse settings with defaults
    raw_settings = raw.get("settings", {})
    settings = Settings(
        detection_interval=raw_settings.get("detection_interval", 0.5),
        tolerance=raw_settings.get("tolerance", 0.6),
        frame_scale=raw_settings.get("frame_scale", 0.25),
        screenshot_dir=raw_settings.get("screenshot_dir", "screenshots"),
        log_dir=raw_settings.get("log_dir", "logs"),
        cooldown=raw_settings.get("cooldown", 10),
    )

    # Parse cameras
    raw_cameras = raw.get("cameras", {})
    if not raw_cameras:
        raise ValueError("No cameras defined in cameras.toml")

    cameras: list[CameraConfig] = []
    for cam_id, cam_data in raw_cameras.items():
        if "url" not in cam_data:
            raise ValueError(f"Camera '{cam_id}' is missing required 'url' field")
        cameras.append(
            CameraConfig(
                id=cam_id,
                name=cam_data.get("name", cam_id),
                url=cam_data["url"],
            )
        )

    logger.info("Loaded {} camera(s) from {}", len(cameras), cameras_path)
    return settings, cameras


def load_webhooks_config(config_dir: Path = DEFAULT_CONFIG_DIR) -> list[WebhookConfig]:
    """Load webhooks.toml and return list of webhook configurations.

    Args:
        config_dir: Path to the configuration directory.

    Returns:
        List of WebhookConfig (only enabled webhooks with valid URLs).
    """
    webhooks_path = config_dir / "webhooks.toml"
    if not webhooks_path.exists():
        logger.warning(
            "Webhook config not found: {} — webhooks disabled", webhooks_path
        )
        return []

    with open(webhooks_path, "rb") as f:
        raw = tomllib.load(f)

    raw_webhooks = raw.get("webhooks", {})
    webhooks: list[WebhookConfig] = []

    for wh_id, wh_data in raw_webhooks.items():
        webhook = WebhookConfig(
            id=wh_id,
            enabled=wh_data.get("enabled", True),
            url=wh_data.get("url", ""),
            method=wh_data.get("method", "POST").upper(),
            headers=wh_data.get("headers", {}),
            body_template=wh_data.get("body_template", ""),
        )
        if webhook.enabled and webhook.url:
            webhooks.append(webhook)
            logger.info("Webhook '{}' loaded: {}", wh_id, webhook.url)
        elif webhook.enabled and not webhook.url:
            logger.warning("Webhook '{}' is enabled but has no URL — skipping", wh_id)

    return webhooks
