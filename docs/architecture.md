---
title: Architecture
description: Threading model, data flow, synchronization, and design decisions
---

# Architecture

> *"He was the best and greatest of giants... he had a hundred eyes, and, wonderful to say, he had them all open."* — Ovid, Metamorphoses

![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-red.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)

---

## Design Philosophy

Argus is built on three principles:

1. **Never crash.** A dropped stream is not a fatal error — it's a reason to reconnect. A failed webhook is not an exception — it's a logged warning. Argus runs indefinitely without intervention.

2. **Never block the eyes.** Detection is the hot path. Everything else — logging, screenshots, webhooks — happens asynchronously. A dead webhook endpoint cannot stall face recognition.

3. **Scale with cameras, not resources.** Twenty cameras should not require twenty machines. Thread-per-camera with 512KB stacks, vectorized matching, and frame downscaling keep the footprint low.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              main.py                                        │
│                    CLI parsing, component wiring, banner                    │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           StreamManager                                     │
│             Orchestrator — main thread, processing loop, signals            │
└───┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────────┘
    │             │             │             │             │
    ▼             ▼             ▼             ▼             ▼
┌────────┐  ┌────────┐  ┌────────┐  ┌──────────────┐  ┌──────────┐
│RTSP    │  │RTSP    │  │RTSP    │  │ Detection    │  │  Alert   │
│Stream  │  │Stream  │  │Stream  │  │  dispatcher  │  │  Handler │
│(cam_01)│  │(cam_02)│  │(cam_N) │  │  + backend   │  │          │
│ thread │  │ thread │  │ thread │  │  main thread │  │ main +   │
│ 512KB  │  │ 512KB  │  │ 512KB  │  │  _INFER_LOCK │  │ daemon   │
└────────┘  └────────┘  └────────┘  └──────────────┘  └──────────┘
                                                      │
                                              ┌───────┴───────┐
                                              │   Display     │
                                              │  (optional)   │
                                              │  main thread  │
                                              │  one window/  │
                                              │  camera       │
                                              └───────────────┘
```

### Module Map

| Module | File | Role |
|---|---|---|
| Entry point | `main.py` | CLI parsing, component wiring, banner output |
| Stream reader | `argus/stream.py` | `RTSPStream` — one daemon thread per camera, FFmpeg-backed, auto-reconnect |
| Face detection | `argus/detection.py` + `argus/detection_models/` | dispatcher + pluggable backends — `dlib_hog` (default), `dlib_cnn`, `insightface`, `facenet` |
| Alert handler | `argus/alert.py` | `AlertHandler` — cooldown enforcement, screenshot capture, webhook dispatch |
| Stream manager | `argus/manager.py` | `StreamManager` — main processing loop, signal handling, GUI tick |
| Display | `argus/display.py` | `Display` — optional OpenCV windows with bounding box overlays |
| Config loader | `argus/config.py` | TOML parsing for cameras and webhooks |
| Data models | `argus/models.py` | Dataclasses — `CameraConfig`, `Settings`, `WebhookConfig`, `Target`, `MatchEvent` |
| Target loader | `argus/targets.py` | Scan `targets/`, compute face encodings, build flat encoding index |

---

## The Processing Pipeline

Every detection pass follows this exact sequence:

```
RTSPStream._run()
    │
    ├─► cv2.VideoCapture.open(url, CAP_FFMPEG)
    │       FFmpeg backend, TCP transport, low-latency flags
    │
    ├─► cap.read() loop (drains RTSP buffer at full speed)
    │       │
    │       └─► self._frame = frame     (under self._lock)
    │
    ▼
StreamManager._main_loop()
    │
    ├─► Time-gate check: elapsed >= detection_interval?
    │
    ├─► stream.latest_frame()
    │       Returns frame.copy() under _lock    ← snapshot semantics
    │
    ├─► detector.detect(frame, camera_id, camera_name)   # resolved Backend
    │       │
    │       ├─► cv2.resize(frame, fx=0.25, fy=0.25)
    │       │       Downscale for speed
    │       │
    │       ├─► cv2.cvtColor(BGR → RGB)
    │       │
    │       ├─► [acquire _DETECTION_LOCK]
    │       │       face_recognition.face_locations(rgb_small, model="hog")
    │       │       face_recognition.face_encodings(rgb_small, face_locations)
    │       │   [release _DETECTION_LOCK]
    │       │
    │       ├─► face_recognition.face_distance(all_encodings, encoding)
    │       │       Vectorized — all targets compared in one call
    │       │
    │       ├─► Filter: best_distance <= tolerance?
    │       │
    │       └─► Return list[MatchEvent] with scaled bboxes
    │
    ├─► For each MatchEvent:
    │       AlertHandler.handle(event)
    │           │
    │           ├─► Cooldown check: (target, camera) pair recent?
    │           │       Skip if within cooldown window
    │           │
    │           ├─► _save_screenshot()
    │           │       Copy frame, draw bbox + label, imwrite JPEG @ 85 quality
    │           │
    │           ├─► logger.success("MATCH: ...")
    │           │       Bound structured data (person, camera, confidence, screenshot)
    │           │       → stderr: colored human-readable format
    │           │       → logs/detections.json: serialized JSON, rotated daily
    │           │
    │           └─► _fire_webhooks()
    │                   For each enabled webhook:
    │                       Thread(target=_send_webhook, daemon=True).start()
    │                           │
    │                           ├─► regex template substitution
    │                           ├─► httpx.request(method, url, content=body, timeout=10)
    │                           └─► log success/warning on failure
    │
    ├─► Display.update(camera_id, frame, matches)
    │       Draw bounding boxes, cv2.imshow()
    │
    └─► Display.tick()
            cv2.waitKey(1), return False if 'q' pressed
```

---

## Threading Model

Argus uses **three classes of threads**:

### 1. Stream Reader Threads (daemon)

- **One per camera.** Named `stream-{camera.id}`.
- **512KB stack.** Set globally via `threading.stack_size(512 * 1024)` before any thread is spawned. The default Python stack is 8MB — irrelevant for a thread that just reads frames and updates a buffer.
- **Owns the `cv2.VideoCapture` instance.** No sharing, no locks around the capture.
- **Writes frames** to `self._frame` under `self._lock` — a lightweight per-stream `threading.Lock`.
- **Reads frames** at full RTSP speed to drain the buffer. The main thread consumes at `detection_interval` rate. This decoupling prevents RTSP buffer buildup.
- **Reconnects automatically** on stream failure with exponential backoff (see below).

### 2. Main Thread (processing loop + GUI)

- **Runs `StreamManager._main_loop()`.** This is the orchestrator — it iterates cameras, grabs frames, runs detection, dispatches alerts, and ticks the GUI.
- **Must be the main thread if GUI is enabled.** OpenCV's `imshow` and `waitKey` require the main thread on most platforms.
- **Handles signals.** `SIGINT` (Ctrl+C) and `SIGTERM` trigger graceful shutdown.
- **10ms sleep** per loop iteration to prevent busy-waiting while staying responsive.

### 3. Webhook Threads (daemon)

- **Spawned per webhook per match event.** Each webhook fires in its own thread.
- **Daemon threads** — they die when the main process exits. No cleanup needed.
- **Fire-and-forget.** A slow or dead endpoint cannot stall the pipeline. The 10-second httpx timeout is the only constraint.
- **No thread reuse.** Each match spawns fresh threads. The overhead is negligible for a system that fires alerts at human-activity rates (not per-frame).

### Thread Interaction Diagram

```
Main Thread
    │
    ├──► stream.latest_frame() ──[lock]──► Stream Thread (_frame buffer)
    │
    ├──► detector.detect() ──[lock]──► _DETECTION_LOCK (serializes dlib)
    │
    ├──► alert_handler.handle()
    │        │
    │        ├──► _save_screenshot()         (main thread, synchronous)
    │        ├──► logger.success()            (main thread, synchronous)
    │        └──► Thread(_send_webhook)       (spawns daemon thread)
    │
    └──► display.tick()                      (main thread, cv2.waitKey)
```

---

## Synchronization

Three locks protect shared state. Each has a single, well-defined purpose:

### `_DETECTION_LOCK` (module-level, `detection.py`)

```python
_DETECTION_LOCK = threading.Lock()
```

**Protects all `face_recognition` / `dlib` calls.** The dlib library uses global singleton objects (detector, encoder) that are not thread-safe. Without this lock, concurrent face detection from multiple camera threads would corrupt dlib's internal state. Every call to `face_recognition.face_locations()` and `face_recognition.face_encodings()` is serialized behind this lock.

**This is the bottleneck by design.** Detection is CPU-bound and dlib is not thread-safe. Serializing it is cheaper than crashing.

### `_lock` (per-stream, `stream.py`)

```python
self._lock = threading.Lock()
```

**Protects the frame buffer** (`self._frame` and `self._has_frame`). The stream reader thread writes; the main thread reads via `latest_frame()`. The read returns a **copy** (`self._frame.copy()`) — snapshot semantics. The main thread never holds a reference to the live buffer.

### `_cooldown_lock` (per-AlertHandler, `alert.py`)

```python
self._cooldown_lock = threading.Lock()
```

**Protects the cooldown dictionary** (`self._cooldowns`). The cooldown check-and-update is not atomic without this lock. Two threads detecting the same target on the same camera simultaneously could both pass the cooldown check and fire duplicate alerts. This lock prevents that race.

---

## Memory Management

### Thread Stack Size

```python
threading.stack_size(512 * 1024)  # 512 KB, called at module import
```

Called once at import time, before any threads are spawned. This applies to **all subsequent threads** in the process. The default Python thread stack is 8MB — Argus reduces it to 512KB because stream reader threads don't need deep call stacks. They read frames, update a buffer, and reconnect on failure.

**Impact at scale:** 20 cameras × 512KB = 10MB of stack memory, versus 160MB at the default. This matters on VMs and containers with tight memory limits.

### Frame Copying Strategy

The stream reader writes frames to `self._frame` under a lock. The consumer reads via `latest_frame()`, which returns `self._frame.copy()` under the same lock.

**Why copy?** The main thread may hold the frame reference for the duration of detection (HOG + encoding + matching) — potentially tens of milliseconds. If the stream reader overwrote `self._frame` during that window, the consumer would operate on a partially-written buffer. The copy guarantees a consistent snapshot.

**Why not a queue?** A queue would buffer multiple frames, increasing memory usage and latency. Argus only cares about the *latest* frame — older frames are stale. The lock-protected single-slot buffer is the minimal correct solution.

---

## Reconnection Strategy

Stream failures are expected, not exceptional. Cameras go offline, networks drop, RTSP servers restart. Argus handles all of this without human intervention.

### Exponential Backoff

```python
_BASE_RECONNECT_DELAY = 1.0   # seconds
_MAX_RECONNECT_DELAY = 60.0   # seconds cap
```

**Formula:** `delay = min(BASE × 2^failures, MAX)`

| Consecutive Failures | Delay |
|---|---|
| 1 | 1s |
| 2 | 2s |
| 3 | 4s |
| 4 | 8s |
| 5 | 16s |
| 6 | 32s |
| 7+ | 60s (capped) |

The delay resets to 0 on successful connection. A stream that briefly drops reconnects in 1 second. A stream that stays down backs off to 60 seconds and stays there.

### Consecutive Read Failures

Inside the read loop, if `cap.read()` returns `False` for **30 consecutive attempts**, the stream is declared dead and reconnection is triggered. This threshold prevents rapid-fire failures from hammering the reconnection logic while still detecting genuine stream death quickly.

### Interruptible Wait

The backoff wait uses `self._stopped.wait(timeout=delay)` — not `time.sleep()`. This means a shutdown signal (`stop()`) interrupts the wait immediately. No hanging during shutdown.

---

## FFmpeg Options

Argus configures FFmpeg's RTSP transport globally via environment variable:

```python
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp"
    "|fflags;nobuffer"
    "|flags;low_delay"
    "|analyzeduration;1000000"
    "|probesize;1000000"
    "|stimeout;5000000"
)
```

| Option | Value | Purpose |
|---|---|---|
| `rtsp_transport` | `tcp` | Force TCP transport. UDP loses packets on congested networks; TCP guarantees delivery. |
| `fflags` | `nobuffer` | Disable FFmpeg's internal buffering. Read frames immediately as they arrive. |
| `flags` | `low_delay` | Minimize decoder latency. Trades quality for speed — appropriate for surveillance. |
| `analyzeduration` | `1000000` (1s) | Limit stream analysis to 1 second. Prevents FFmpeg from spending minutes probing slow streams. |
| `probesize` | `1000000` (~1MB) | Limit probing data to 1MB. Same rationale — don't waste time analyzing huge chunks. |
| `stimeout` | `5000000` (5s) | Socket timeout. If no data arrives in 5 seconds, consider the connection dead. |

These options are set **before any `VideoCapture` is created** — they apply process-wide to all FFmpeg-backed captures.

---

## Signal Handling

```python
signal.signal(signal.SIGINT, self._signal_handler)
signal.signal(signal.SIGTERM, self._signal_handler)
```

Both `SIGINT` (Ctrl+C) and `SIGTERM` (kill, systemd stop) trigger the same handler: set `self._running = False`. The main loop checks this flag at the top of every iteration and exits cleanly.

### Shutdown Sequence

1. **Signal received** → `_running = False`
2. **Main loop exits** → enters `finally` block
3. **`_shutdown()` called** → iterates all streams, calls `stream.stop()` on each
4. **`stream.stop()`** → sets `self._stopped` event, which:
   - Interrupts any in-progress reconnection wait
   - Causes the stream reader's `while not self._stopped.is_set()` loop to exit
5. **Display destroyed** → `cv2.destroyAllWindows()`
6. **Log message** → `"Argus stopped. All-seeing eyes closed."`

All stream threads are daemons — they die with the process anyway. But the explicit `stop()` call ensures they exit promptly rather than waiting for the GC.

---

## Error Handling Philosophy

**Argus does not crash.** Every failure mode has a recovery path:

| Failure | Response |
|---|---|
| Camera unreachable | Log warning, exponential backoff, retry forever |
| Stream drops mid-read | Log warning after 30 consecutive failures, reconnect |
| No target images loaded | Warning — detection still runs, identification disabled |
| Target image has no face | Warning — that image skipped, other images still used |
| Webhook endpoint down | Log warning, skip, try again on next match |
| Webhook timeout (10s) | Log warning, continue |
| Invalid webhook template | Log error with placeholder name, skip that webhook |
| Bad `info.json` (malformed) | Log error, skip that target |
| Missing image file | Log warning, skip that image |
| Config file missing | `FileNotFoundError` → log error, `sys.exit(1)` — this is the one hard failure, because running with no config is pointless |
| GUI unavailable | Not handled explicitly — OpenCV will raise if display is unavailable, which is acceptable for a GUI feature |

The only intentional exit codes are:

- `sys.exit(1)` — configuration error (missing or invalid `cameras.toml`)
- `KeyboardInterrupt` — caught by the main loop, triggers clean shutdown

Everything else recovers.

---

## Data Models

All data flows through typed dataclasses defined in `argus/models.py`:

### CameraConfig

```python
@dataclass
class CameraConfig:
    id: str        # TOML key (e.g., "cam_01")
    name: str      # Human-readable name (e.g., "Front Door")
    url: str       # RTSP stream URL
```

### Settings

```python
@dataclass
class Settings:
    detection_interval: float = 0.5   # seconds between detection passes
    tolerance: float = 0.6            # face distance threshold
    frame_scale: float = 0.25         # downscale factor
    screenshot_dir: str = "screenshots"
    log_dir: str = "logs"
    cooldown: int = 10                # seconds before re-alert
```

Validated in `__post_init__` — `frame_scale` and `tolerance` must be in `(0, 1]`, `detection_interval` must be `> 0`.

### MatchEvent

```python
@dataclass
class MatchEvent:
    target_name: str                        # who was matched
    camera_id: str                          # which camera
    camera_name: str                        # human-readable camera name
    confidence: float                       # 1.0 - distance (higher = better)
    timestamp: datetime                     # UTC, ISO 8601
    bbox: tuple[int, int, int, int]         # (top, right, bottom, left) in original coords
    frame: np.ndarray | None = None         # full-res BGR frame (for screenshots)
```

The `frame` field is excluded from `__repr__` to avoid dumping raw pixel data into logs.

---

## Logging

Argus uses **loguru** with two sinks:

### Console Sink (stderr)

```
14:32:01 | INFO     | argus.stream:_run | [cam_01] Connected to 'Front Door'
```

Colored, human-readable, timestamped. Level: `INFO` and above.

### Structured JSON Sink (`logs/detections.json`)

```json
{
  "text": "MATCH: 'John Doe' on 'Front Door' (confidence: 92.3%)",
  "record": {
    "time": {"timestamp": "2025-01-15T14:35:12.345Z"},
    "level": {"name": "SUCCESS"},
    "extra": {
      "person": "John Doe",
      "camera": "Front Door",
      "camera_id": "cam_01",
      "confidence": 0.923,
      "screenshot": "screenshots/2025-01-15_14-35-12_345678_cam_01_John Doe.jpg"
    }
  }
}
```

Machine-parseable. Rotated daily at midnight. Retained for 30 days. Compressed to zip on rotation.

---

*Argus is always watching. The question is whether you're watching back.*
