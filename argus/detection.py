"""Face detection and recognition — dispatcher, not a class.

This module is intentionally thin. It reads the configured ``model_backend``
and ``use_gpu`` from :class:`Settings`, resolves the matching backend from
:mod:`argus.detection_models`, attaches the target gallery, and exposes the
ready instance as ``FaceDetector``.

``FaceDetector`` is a *variable* holding whichever backend is configured —
``dlib_hog`` (default, everywhere), ``dlib_cnn``, ``insightface``, or
``facenet``. The rest of Argus calls ``detector.detect(...)`` identically no
matter which model is running.
"""

from __future__ import annotations

import numpy as np
from loguru import logger

from argus.detection_models import Backend, available_backends, get_backend
from argus.models import Settings

# Import backend modules so their @register decorators populate the registry.
from argus.detection_models import dlib_based  # noqa: F401
from argus.detection_models import insightface_model  # noqa: F401
from argus.detection_models import facenet_model  # noqa: F401


def resolve_backend(settings: Settings, use_gpu: bool | None = None) -> Backend:
    """Resolve and build the configured face recognition backend (no gallery).

    Reads ``settings.model_backend`` and ``settings.use_gpu``, validates the
    backend and its dependencies, and loads its models. The returned backend
    has no target gallery attached yet — callers attach it with
    :meth:`Backend.set_gallery` after computing target encodings with the
    same backend.

    Args:
        settings: Global settings (tolerance, frame_scale, model_backend, ...).
        use_gpu: Override ``settings.use_gpu`` if provided.

    Returns:
        A constructed backend ready for gallery attachment + ``detect()``.

    Raises:
        ValueError: If the configured backend is unknown or its dependencies
            are not installed.
    """
    gpu = settings.use_gpu if use_gpu is None else bool(use_gpu)
    name = settings.model_backend

    logger.debug(
        "Resolving face backend '{}' (gpu={}) — available: {}",
        name,
        gpu,
        available_backends(),
    )

    backend = get_backend(name, settings=settings, use_gpu=gpu)

    logger.info(
        "Face backend '{}' — metric={}, dim={}, gpu={}",
        backend.name,
        backend.metric,
        backend.dim,
        backend._use_gpu,
    )
    return backend


def FaceDetector(
    all_encodings: np.ndarray | None,
    encoding_names: list[str],
    settings: Settings,
    use_gpu: bool | None = None,
) -> Backend:
    """Build the configured backend and attach the target gallery.

    Convenience wrapper over :func:`resolve_backend` that also attaches the
    target gallery — equivalent to the old :class:`FaceDetector` class usage.
    Prefer :func:`resolve_backend` + :meth:`Backend.set_gallery` when target
    encodings must be computed with the same backend (as in main.py).

    Args:
        all_encodings: (N, D) array of all target encodings, or None.
        encoding_names: List of target names, one per encoding row.
        settings: Global settings.
        use_gpu: Override ``settings.use_gpu`` if provided.

    Returns:
        A backend ready for ``detect()``.
    """
    backend = resolve_backend(settings, use_gpu)
    backend.set_gallery(all_encodings, encoding_names)
    return backend
