# Module Overview

Argus is nine modules and one entry point. Each owns a single responsibility. The data flows one direction — frames in, alerts out.

---

## Dependency Graph

```
main.py
  │
  ├──► config          (loads TOML → models)
  ├──► targets         (loads faces → models)
  │
  ├──► alert           (uses models, webhooks, screenshots)
  ├──► detection       (uses models, face_recognition)
  ├──► display         (uses models, cv2)
  │
  └──► manager         (orchestrates stream, detection, alert, display)
        │
        └──► stream    (one per camera, daemon threads)
```

```
models.py  ◄──── Every module imports from here. Zero dependencies on others.
  ▲
  │
config.py  ──► models.py (CameraConfig, Settings, WebhookConfig)
targets.py ──► models.py (Target)
stream.py  ──► models.py (CameraConfig)
detection.py ──► models.py (MatchEvent, Settings)
alert.py   ──► models.py (MatchEvent, Settings, WebhookConfig)
display.py ──► models.py (CameraConfig, MatchEvent)
manager.py ──► stream, detection, alert, display, models
main.py    ──► config, targets, detection, alert, display, manager
```

---

## Module Responsibilities

| Module | File | Responsibility |
|--------|------|----------------|
| **models** | `argus/models.py` | Dataclass definitions. The contract between every other module. Zero logic beyond `__post_init__` validation. |
| **config** | `argus/config.py` | TOML parsing and validation. Loads `cameras.toml` and `webhooks.toml` into typed dataclasses. Fails loud on bad config. |
| **targets** | `argus/targets.py` | Scans the target database, reads `info.json`, computes 128-D face encodings via `face_recognition`, and builds a flattened index for vectorized matching. |
| **stream** | `argus/stream.py` | One resilient RTSP reader per camera. Daemon thread, auto-reconnect with exponential backoff, lock-protected frame delivery. The eyes never close. |
| **detection** | `argus/detection.py` | Face detection (HOG) and recognition (128-D encoding comparison). Serializes all `face_recognition` calls behind a global lock because dlib's singletons aren't thread-safe. |
| **alert** | `argus/alert.py` | Match event processing: structured logging, annotated screenshot capture, webhook dispatch. Enforces per-(target, camera) cooldown to kill spam. |
| **display** | `argus/display.py` | Optional GUI. One OpenCV window per camera with bounding box overlays. All `cv2` calls enforced to the main thread. |
| **manager** | `argus/manager.py` | The orchestrator. Spawns streams, runs the main loop, time-gates detection, wires everything together. Owns the process lifecycle. |
| **main** | `main.py` | Entry point. Argument parsing, component wiring, banner. Imports happen inside `main()` to avoid side effects at import time. |

---

## Thread Ownership

| Thread | Owner | Purpose |
|--------|-------|---------|
| **Main thread** | `manager.py` | Runs `_main_loop()`, calls `display.update()` and `display.tick()`. **Must** be the main thread if GUI is enabled — `cv2.imshow`/`cv2.waitKey` enforce this. |
| **`stream-{id}`** (×N) | `stream.py` | One per camera. Daemon thread. Continuously reads RTSP frames into a lock-protected buffer. |
| **`ThreadPool` workers** | `alert.py` | Fire-and-forget webhook calls in daemon threads. Spawned per webhook per match event. |

**Lock contention points:**

- `RTSPStream._lock` — protects `_frame` between the reader thread and the main thread's `latest_frame()` call.
- `FaceDetector._DETECTION_LOCK` — module-level, serializes all `face_recognition` calls across all threads (dlib global state).
- `AlertHandler._cooldown_lock` — protects the `_cooldowns` dict between the main thread and any future concurrent `handle()` calls.

---

## Startup Sequence

```
main.py::main()
  1. parse_args()
  2. load_cameras_config()    → Settings, list[CameraConfig]
  3. load_webhooks_config()   → list[WebhookConfig]
  4. AlertHandler()           → sets up loguru sinks, creates dirs
  5. load_targets()           → list[Target]
  6. build_encoding_index()   → (N,128) array, names list
  7. FaceDetector()           → ready to detect
  8. Display() [if --gui]     → creates windows
  9. StreamManager()          → stores references
  10. manager.start()         → spawns threads, enters main loop (blocks)
```
