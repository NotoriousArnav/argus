---
title: Contributing to Argus
description: Code style, architecture decisions, and development setup
---

# Contributing to Argus

---

## Project Structure

```
argus/
├── main.py                 # Entry point — CLI parsing, component wiring
├── config/
│   ├── cameras.toml        # Camera URLs, detection settings
│   └── webhooks.toml       # Webhook endpoints
├── targets/                # Face reference data (per-person directories)
├── argus/
│   ├── __init__.py
│   ├── models.py           # Dataclasses: Settings, CameraConfig, MatchEvent, etc.
│   ├── config.py           # TOML config loading and validation
│   ├── stream.py           # RTSPStream — one thread per camera, auto-reconnect
│   ├── detection.py        # FaceDetector — HOG detection + encoding + matching
│   ├── alert.py            # AlertHandler — logging, screenshots, webhooks
│   ├── display.py          # GUI display windows (OpenCV)
│   ├── manager.py          # StreamManager — orchestrates the full pipeline
│   └── targets.py          # Target loading and encoding index construction
├── screenshots/            # Output — annotated match images (git-ignored)
├── logs/                   # Output — structured JSON logs (git-ignored)
├── pyproject.toml          # Project metadata, dependencies
└── LICENSE                 # GPL-3.0
```

---

## Code Style

### Python 3.12+

Use modern Python. Type hints on everything. F-strings over `.format()`. `match` statements where appropriate. No compatibility shims for older versions.

```python
# Good
def get_frame(self) -> tuple[bool, np.ndarray | None]:
    ...

# Bad
def get_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
    ...
```

### No comments unless asked

The code should be self-documenting. If it needs a comment, rewrite the code. The one exception: docstrings on all public methods.

### Docstrings — Google style

```python
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
```

### Logging — loguru only

Never `print()`. Never `logging`. Always `loguru`.

```python
from loguru import logger

logger.info("[{}] Connected to '{}'", self.camera.id, self.camera.name)
logger.warning("{} consecutive read failures — reconnecting", failures)
```

Use structured logging for match events:

```python
logger.bind(person=name, camera=camera, confidence=score).success(
    "MATCH: '{}' on '{}' (confidence: {:.1%})", name, camera, score
)
```

### Type hints on all function signatures

No exceptions. Parameter types and return types. Always.

---

## Development Setup

### Prerequisites

- **Python 3.12** (required — uses `tomllib` from stdlib, modern type syntax)
- **System dependencies for dlib:**

```bash
# Debian/Ubuntu
sudo apt install cmake libboost-all-dev libdlib-dev

# macOS
brew install cmake boost dlib
```

### Install

```bash
git clone https://github.com/<your-org>/argus.git
cd argus
uv sync
```

This creates a `.venv` with all dependencies. Use `uv run python main.py` to execute.

---

## Architecture Decisions

These patterns are not optional. They exist for specific reasons.

### Thread safety: `_DETECTION_LOCK`

The `face_recognition` library (and dlib underneath) uses **global singleton objects** that are not thread-safe. All calls to `face_recognition.face_locations()`, `face_recognition.face_encodings()`, and `face_recognition.face_distance()` must go through the module-level `_DETECTION_LOCK` in `argus/detection.py`.

Do not call `face_recognition` functions outside this lock. Do not create a second detector. Do not try to parallelize detection across cameras — the global lock serializes it anyway.

### Fire-and-forget webhooks

Webhook calls **never block the detection pipeline**. They run in daemon threads. If a webhook times out or fails, the detection loop does not care. It already moved on.

```python
# This is the pattern
thread = threading.Thread(target=self._send_webhook, args=(...), daemon=True)
thread.start()
# No .join(), no return value, no error handling in the caller
```

### Cooldown system

Cooldowns are keyed on `(target_name, camera_id)` tuples. This means:

- Same person, same camera → cooldown applies (don't spam alerts)
- Same person, different cameras → independent cooldowns (alert on both)
- Different people, same camera → independent cooldowns (alert on both)

The cooldown dictionary is protected by `_cooldown_lock`. Use `time.monotonic()` — never wall clock time — for interval calculations.

### Frame copying under lock

When a consumer calls `stream.latest_frame()`, it receives a **copy** of the frame, not a reference. The lock is held only during the copy. This prevents race conditions between the reader thread (writing frames) and the detection thread (reading frames).

```python
with self._lock:
    if self._has_frame and self._frame is not None:
        return True, self._frame.copy()  # Always copy
    return False, None
```

### Main thread constraint

The GUI (`Display`) must be updated from the main thread. `StreamManager.start()` runs the main loop on the calling thread specifically for this reason. Never move GUI operations to a background thread — OpenCV's `imshow` and `waitKey` require the main thread.

---

## Adding a New Module

### Where it fits

| Module | Responsibility |
|---|---|
| `models.py` | Data structures only — dataclasses, no logic |
| `config.py` | Loading and validation of config files |
| `stream.py` | RTSP stream reading and reconnection |
| `detection.py` | Face detection and recognition (dlib) |
| `alert.py` | Response to match events (log, screenshot, webhook) |
| `display.py` | GUI rendering (OpenCV windows) |
| `manager.py` | Orchestration — ties everything together |
| `targets.py` | Target data loading and encoding construction |

If your module handles a new output type (e.g., database storage, MQTT), it belongs alongside `alert.py`. If it handles a new input type (e.g., ONVIF discovery), it belongs alongside `config.py` or `stream.py`.

### Connecting to StreamManager

The `StreamManager` is the central orchestrator. Components interact with it in one of two ways:

1. **Direct injection** — The manager receives components via `__init__` (detector, alert handler, display). Add constructor parameters for new components.
2. **Event flow** — Data flows: `RTSPStream` → `FaceDetector.detect()` → `AlertHandler.handle()`. To add a new event type, intercept at the manager's main loop.

### Threading considerations

- New output handlers must be **non-blocking** (fire-and-forget threads or queues)
- Never acquire `_DETECTION_LOCK` from a webhook handler
- Never call GUI operations from a background thread

---

## Adding a New Alert Type

### Option 1: Extend AlertHandler

Add a new method to `AlertHandler` and call it from `handle()`:

```python
def handle(self, event: MatchEvent) -> None:
    if self._is_on_cooldown(event.target_name, event.camera_id):
        return
    self._update_cooldown(event.target_name, event.camera_id)
    self._save_screenshot(event)
    self._log_match(event)
    self._new_alert_type(event)  # Add your handler here
    self._fire_webhooks(event)
```

### Option 2: Create a new handler class

If the alert type has its own state, lifecycle, or configuration, create a separate class. Accept it in `StreamManager.__init__` and call it from the main loop.

### Requirements

- Must not block the detection pipeline
- Must integrate with the cooldown system (check before acting, update after)
- Must handle its own errors internally — never let an alert failure crash the pipeline
- Must use loguru for logging

---

## Testing

No test suite exists yet. Testing is manual.

### Creating test RTSP streams

Use ffmpeg to create synthetic test streams:

```bash
# Generate a test pattern stream on localhost
ffmpeg -f lavfi -i testsrc=size=1280x720:rate=30 \
  -c:v libx264 -preset ultrafast \
  -f rtsp rtsp://127.0.0.1:8554/test

# Re-stream a video file as RTSP
ffmpeg -re -i sample_video.mp4 \
  -c:v libx264 -preset ultrafast \
  -f rtsp rtsp://127.0.0.1:8554/test
```

### Testing face recognition

1. Create a target directory with reference images
2. Run a test stream with faces visible (use your webcam or a video of faces)
3. Verify matches appear in logs
4. Verify screenshots are saved with correct annotations
5. Verify webhooks fire (check your receiver logs)

### What to test

- Connection to multiple cameras simultaneously
- Reconnection after killing a test stream (Ctrl+C the ffmpeg process)
- Cooldown behavior (same person, same camera)
- Cooldown independence (same person, different cameras)
- Webhook failure handling (point webhook at a down server)
- Graceful shutdown (SIGTERM via `kill <pid>`)

---

## Commit Style

Short, imperative. Match the existing history.

```
Working finally
LICENSE
fix stream reconnection
add cooldown per target-camera
```

No conventional commits prefix required. No body text required. Just say what changed.
