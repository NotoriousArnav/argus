# Manager

The brain stem. Orchestrates every component. Runs the main loop. Owns the process.

---

## StreamManager

```python
class StreamManager:
    """Orchestrates the full Argus pipeline.
    - Spawns one RTSPStream thread per camera.
    - Runs the main processing loop on the calling thread (must be main thread if GUI).
    - For each camera, grabs the latest frame at `detection_interval` rate.
    - Runs face detection/recognition and dispatches matches to the alert handler.
    - Optionally updates the GUI display."""
```

### Constructor

```python
def __init__(
    self,
    settings: Settings,
    cameras: list[CameraConfig],
    detector: FaceDetector,
    alert_handler: AlertHandler,
    display: Display | None = None,
) -> None:
```

| Attribute | Type | Purpose |
|-----------|------|---------|
| `_settings` | `Settings` | Global configuration |
| `_cameras` | `list[CameraConfig]` | Camera list |
| `_detector` | `FaceDetector` | Face detection engine |
| `_alert_handler` | `AlertHandler` | Match event processor |
| `_display` | `Display \| None` | GUI (None in headless mode) |
| `_streams` | `dict[str, RTSPStream]` | Camera ID → stream thread |
| `_last_detection_time` | `dict[str, float]` | Camera ID → `time.monotonic()` of last detection |
| `_running` | `bool` | Main loop control flag |

---

## `start()`

```python
def start(self) -> None:
```

**Blocks until interrupted.** Must be called from the main thread if GUI is enabled.

### Sequence

```
1. Set _running = True
2. Register signal handlers (SIGINT, SIGTERM)
3. Spawn one RTSPStream per camera
   → Each spawns a daemon thread immediately
   → Initialize _last_detection_time to 0.0 (first detection fires immediately)
4. Enter _main_loop()
5. On exit (KeyboardInterrupt or 'q' key): _shutdown()
```

### Why Main Thread?

`cv2.imshow()` and `cv2.waitKey()` **must** run on the main thread. This is an OpenCV/Qt/macOS constraint — not a design choice. The main loop runs here to satisfy this. In headless mode it doesn't matter, but the code doesn't branch for it.

---

## `_main_loop()`

```python
def _main_loop(self) -> None:
```

The heartbeat. Runs at roughly 100 Hz (10ms sleep per iteration).

```
while _running:
    now = time.monotonic()

    for each camera:
        # Time-gate: skip if not enough time has elapsed
        if (now - last_detection_time) < interval:
            continue

        # Grab latest frame
        ok, frame = stream.latest_frame()
        if not ok: continue

        # Record detection time
        last_detection_time = now

        # Run detection
        matches = detector.detect(frame, camera.id, camera.name)

        # Handle matches
        for event in matches:
            alert_handler.handle(event)

        # Update display
        display.update(camera.id, frame, matches)

    # GUI tick — processes window events, checks for 'q' key
    if not display.tick():
        _running = False
        break

    # Prevent busy-wait
    time.sleep(0.01)
```

### Time-Gated Detection

Each camera has its own detection timer. With `detection_interval = 0.5`, each camera is checked every 0.5 seconds — not simultaneously. Cameras are checked sequentially in the loop, so there's natural staggering.

### The 10ms Sleep

```python
time.sleep(0.01)
```

Without this, the loop spins at 100% CPU doing nothing useful. With 10ms, CPU usage drops to near-zero during idle periods while remaining responsive. The detection interval timer is independent — the sleep doesn't affect detection timing.

**What happens without it?** CPU pegs at 100%. The detection timer still works (it's monotonic-time based), but the system burns power and generates heat for zero benefit.

---

## Signal Handling

```python
def _signal_handler(self, signum: int, _frame: object) -> None:
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    self._running = False
```

Sets `_running = False`. The main loop exits on the next iteration. No force-kill, no orphaned threads — daemon threads die with the process.

Also caught: `KeyboardInterrupt` in the `try` block around `_main_loop()`. Same result — falls through to `_shutdown()`.

---

## `_shutdown()`

```python
def _shutdown(self) -> None:
```

Clean teardown order:

```
1. Stop all RTSPStream threads
   → Each sets _stopped event
   → Reader threads exit their loops
   → Daemon threads die with the process (guaranteed)

2. Destroy display windows
   → cv2.destroyAllWindows()

3. Log "All-seeing eyes closed."
```

Streams are stopped **first** — no new frames arrive during display teardown. Display is destroyed **last** — the operator sees the final state until windows close.

---

## Component Lifecycle

```
main.py creates:          StreamManager owns:
─────────────             ──────────────────
Settings                  _settings (reference)
list[CameraConfig]        _cameras (reference)
FaceDetector              _detector (reference)
AlertHandler              _alert_handler (reference)
Display | None            _display (reference)
                          _streams (dict, created in start())
                          _last_detection_time (dict, created in start())
```

The manager doesn't **own** the components — it receives them fully initialized. It's the orchestrator, not the factory. `main.py` builds everything, hands it to the manager, and calls `start()`.
