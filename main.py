"""Argus — Multi-camera RTSP surveillance with face recognition.

Usage:
    python main.py                      # Headless mode (default)
    python main.py --gui                # With live camera display windows
    python main.py --config /path/to    # Custom config directory
    python main.py --targets /path/to   # Custom targets directory
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

# Suppress pkg_resources deprecation warning from face_recognition_models
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

from loguru import logger

BANNER = r"""
     _
    / \   _ __ __ _ _   _ ___
   / _ \ | '__/ _` | | | / __|
  / ___ \| | | (_| | |_| \__ \
 /_/   \_\_|  \__, |\__,_|___/
              |___/
  All-Seeing Surveillance System
"""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Argus — Multi-camera RTSP surveillance with face recognition",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        default=False,
        help="Enable live camera display windows (one per camera)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config"),
        help="Path to configuration directory (default: config/)",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("targets"),
        help="Path to targets directory (default: targets/)",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for Argus."""
    args = parse_args()

    # Import here to avoid import-time side effects (e.g., OpenCV env vars)
    # before argument parsing is complete.
    from argus.alert import AlertHandler
    from argus.config import load_cameras_config, load_webhooks_config
    from argus.detection import resolve_backend
    from argus.display import Display
    from argus.manager import StreamManager
    from argus.targets import build_encoding_index, load_targets

    # --- Banner ---
    sys.stderr.write(BANNER + "\n")
    sys.stderr.flush()

    # --- Load configuration ---
    # Config loading uses the default loguru sink (before AlertHandler reconfigures it).
    # This is fine — the first few log lines will use the verbose format.
    try:
        settings, cameras = load_cameras_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Configuration error: {}", e)
        sys.exit(1)

    webhooks = load_webhooks_config(args.config)

    # --- Initialize alert handler (sets up loguru sinks for the rest of the session) ---
    alert_handler = AlertHandler(settings, webhooks)

    logger.info(
        "Configuration loaded: {} camera(s), {} webhook(s)", len(cameras), len(webhooks)
    )

    # --- Resolve the face recognition backend ---
    # argus.detection decides which model to use from config, validates its
    # dependencies, and loads it. The SAME instance is used for both target
    # encoding and live detection so embeddings are always comparable.
    try:
        backend = resolve_backend(settings)
    except ValueError as e:
        logger.error("Backend error: {}", e)
        sys.exit(1)

    # --- Load targets (encodings use the same backend as live detection) ---
    logger.info("Loading targets from {}", args.targets)
    targets = load_targets(args.targets, backend=backend)
    all_encodings, encoding_names = build_encoding_index(targets)
    backend.set_gallery(all_encodings, encoding_names)

    if not targets:
        logger.warning(
            "No targets loaded — Argus will detect faces but cannot identify anyone"
        )

    display = None
    if args.gui:
        logger.info("GUI mode enabled — spawning {} window(s)", len(cameras))
        display = Display(cameras)
    else:
        logger.info("Headless mode — no display windows")

    # --- Start the manager ---
    manager = StreamManager(
        settings=settings,
        cameras=cameras,
        detector=backend,
        alert_handler=alert_handler,
        display=display,
    )

    logger.info(
        "Starting Argus: {} camera(s), {} target(s), {} webhook(s)",
        len(cameras),
        len(targets),
        len(webhooks),
    )

    manager.start()


if __name__ == "__main__":
    main()
