# Models

The data contract. Every module imports from here. Nothing else imports from anywhere else.

---

## CameraConfig

```python
@dataclass
class CameraConfig:
    """Configuration for a single RTSP camera."""

    id: str
    name: str
    url: str
```

| Field | Type | Source |
|-------|------|--------|
| `id` | `str` | TOML key under `[cameras]` — e.g., `cam_01` |
| `name` | `str` | `cam_data.get("name", cam_id)` — falls back to the ID |
| `url` | `str` | **Required.** RTSP stream URL. Missing = `ValueError` at load time. |

**No validation beyond existence.** The URL is tested when `RTSPStream` tries to connect, not at parse time.

---

## Settings

```python
@dataclass
class Settings:
    """Global detection and runtime settings."""

    detection_interval: float = 0.5
    tolerance: float = 0.6
    frame_scale: float = 0.25
    screenshot_dir: str = "screenshots"
    log_dir: str = "logs"
    cooldown: int = 10
```

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `detection_interval` | `float` | `0.5` | Must be `> 0`. Seconds between detection passes per camera. |
| `tolerance` | `float` | `0.6` | Must be in `(0, 1]`. Face distance threshold — lower is stricter. |
| `frame_scale` | `float` | `0.25` | Must be in `(0, 1]`. Downscale factor before detection. `0.25` = 4× reduction. |
| `screenshot_dir` | `str` | `"screenshots"` | No validation. Created at `AlertHandler` init. |
| `log_dir` | `str` | `"logs"` | No validation. Created at `AlertHandler` init. |
| `cooldown` | `int` | `10` | No explicit validation (implicitly must be ≥ 0). Seconds before re-alerting. |

### `__post_init__` Validation Rules

```python
def __post_init__(self) -> None:
    if not 0.0 < self.frame_scale <= 1.0:
        raise ValueError(f"frame_scale must be in (0, 1], got {self.frame_scale}")
    if not 0.0 < self.tolerance <= 1.0:
        raise ValueError(f"tolerance must be in (0, 1], got {self.tolerance}")
    if self.detection_interval <= 0:
        raise ValueError(
            f"detection_interval must be > 0, got {self.detection_interval}"
        )
```

Fires at construction time. If you pass bad values from TOML, `ValueError` propagates up through `load_cameras_config()` and `main.py` exits with code 1.

---

## WebhookConfig

```python
@dataclass
class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    id: str
    enabled: bool = True
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body_template: str = ""
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | `str` | — | TOML key under `[webhooks]`. |
| `enabled` | `bool` | `True` | Disabled webhooks are filtered out at load time. |
| `url` | `str` | `""` | **Skipped if empty**, even if `enabled = true`. |
| `method` | `str` | `"POST"` | Uppercased at load time. |
| `headers` | `dict[str, str]` | `{}` | Merged with `Content-Type: application/json` at send time. |
| `body_template` | `str` | `""` | JSON body with `{placeholder}` patterns. Not `str.format()` — regex substitution. |

---

## Target

```python
@dataclass
class Target:
    """A surveillance target with pre-computed face encodings."""

    name: str
    encodings: list[np.ndarray] = field(default_factory=list)
```

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | Display name from `info.json`, or the directory name as fallback. |
| `encodings` | `list[np.ndarray]` | Each array is `(128,)` — a 128-D face encoding from `face_recognition`. Multiple images = multiple encodings. |

A target with zero encodings is discarded at load time. It never makes it to the detector.

---

## MatchEvent

```python
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
```

| Field | Type | Notes |
|-------|------|-------|
| `target_name` | `str` | Matched target's display name. |
| `camera_id` | `str` | Camera identifier. |
| `camera_name` | `str` | Human-readable camera name. |
| `confidence` | `float` | `1.0 - best_distance`. Range: `(0, 1]`. Higher = better match. |
| `timestamp` | `datetime` | UTC, set at detection time. |
| `bbox` | `tuple[int, int, int, int]` | **(top, right, bottom, left)** — dlib's format. **Not** `(x, y, w, h)`. |
| `frame` | `np.ndarray \| None` | The original full-resolution BGR frame. `repr=False` to avoid dumping a 1080p numpy array into log output. Used downstream for screenshot annotation. |

### The `bbox` Tuple

dlib and `face_recognition` return bounding boxes as `(top, right, bottom, left)` — the coordinates of the top-right and bottom-left corners. This is **not** the OpenCV convention of `(x, y, w, h)`.

When passing to `cv2.rectangle()`:

```python
# Correct: cv2 uses (left, top) → (right, bottom)
cv2.rectangle(frame, (left, top), (right, bottom), color, thickness)
```

The `top`/`left` values may be **smaller** than `bottom`/`right` — this is normal. They're pixel coordinates, not dimensions.

### `frame` Lifecycle

1. `FaceDetector.detect()` attaches `frame` (the original BGR array) to the `MatchEvent`.
2. `AlertHandler._save_screenshot()` copies it and draws the bounding box + label.
3. The annotated copy is written to disk as JPEG.
4. The original reference is discarded when the `MatchEvent` goes out of scope.

The `repr=False` prevents loguru from attempting to serialize the numpy array when `MatchEvent` is logged. Without it, you'd get multi-megabyte log entries.
