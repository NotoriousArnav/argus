"""Target loading — scan targets/ directory and pre-compute face encodings.

Target encodings MUST be computed with the same backend used for live
detection — mixing backends (e.g. dlib HOG gallery + InsightFace live) will
silently break matching, because each model produces incomparable embeddings.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from loguru import logger

from argus.models import Target

DEFAULT_TARGETS_DIR = Path("targets")


def load_targets(
    targets_dir: Path = DEFAULT_TARGETS_DIR,
    backend=None,
) -> list[Target]:
    """Scan targets directory, load info.json for each, and compute encodings.

    Directory structure expected:
        targets/
            <name>/
                info.json      {"name": "...", "images": ["face1.jpg", ...]}
                face1.jpg
                ...

    Args:
        targets_dir: Path to the targets root directory.
        backend: The active :class:`Backend` used to compute encodings. Must
            be the same backend used for live detection.

    Returns:
        List of Target objects with pre-computed embeddings.
    """
    if not targets_dir.exists():
        logger.warning(
            "Targets directory not found: {} — no targets loaded", targets_dir
        )
        return []

    targets: list[Target] = []

    for target_path in sorted(targets_dir.iterdir()):
        if not target_path.is_dir():
            continue

        info_path = target_path / "info.json"
        if not info_path.exists():
            logger.warning("No info.json in {} — skipping", target_path)
            continue

        target = _load_single_target(target_path, info_path, backend)
        if target is not None:
            targets.append(target)

    logger.info(
        "Loaded {} target(s) with {} total encoding(s)",
        len(targets),
        sum(len(t.encodings) for t in targets),
    )
    return targets


def _load_single_target(
    target_path: Path, info_path: Path, backend
) -> Target | None:
    """Load a single target from its directory.

    Args:
        target_path: Path to the target's directory.
        info_path: Path to the target's info.json.
        backend: The active backend for computing encodings.

    Returns:
        A Target with encodings, or None if no valid encodings found.
    """
    try:
        with open(info_path) as f:
            info = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read {}: {}", info_path, e)
        return None

    name = info.get("name", target_path.name)
    image_files = info.get("images", [])

    if not image_files:
        logger.warning("Target '{}' has no images listed — skipping", name)
        return None

    encodings: list[np.ndarray] = []

    for img_file in image_files:
        img_path = target_path / img_file
        if not img_path.exists():
            logger.warning("Image not found for target '{}': {}", name, img_path)
            continue

        encoding = _compute_encoding(img_path, name, backend)
        if encoding is not None:
            encodings.append(encoding)

    if not encodings:
        logger.error("Target '{}' has no valid face encodings — skipping", name)
        return None

    logger.info("Target '{}' loaded with {} encoding(s)", name, len(encodings))
    return Target(name=name, encodings=encodings)


def _compute_encoding(img_path: Path, target_name: str, backend) -> np.ndarray | None:
    """Compute an embedding from an image file using the active backend.

    Args:
        img_path: Path to the image file.
        target_name: Name of the target (for logging).
        backend: The active backend used for encoding.

    Returns:
        Embedding vector, or None if no face detected.
    """
    try:
        image = backend.ndarray_from_file(str(img_path))
    except Exception as e:
        logger.error("Failed to load image {} for '{}': {}", img_path, target_name, e)
        return None

    face_encs = backend.encode_image(image)

    if not face_encs:
        logger.warning("No face detected in {} for target '{}'", img_path, target_name)
        return None

    if len(face_encs) > 1:
        logger.warning(
            "Multiple faces in {} for target '{}' — using first face",
            img_path,
            target_name,
        )

    return face_encs[0]


def build_encoding_index(
    targets: list[Target],
) -> tuple[np.ndarray | None, list[str]]:
    """Build a flattened encoding matrix and name mapping for fast vectorized comparison.

    Args:
        targets: List of loaded targets.

    Returns:
        Tuple of:
            - all_encodings: (N, 128) numpy array of all target encodings, or None if empty.
            - encoding_names: List of target names, one per encoding row.
    """
    if not targets:
        return None, []

    all_encodings: list[np.ndarray] = []
    encoding_names: list[str] = []

    for target in targets:
        for enc in target.encodings:
            all_encodings.append(enc)
            encoding_names.append(target.name)

    return np.array(all_encodings), encoding_names
