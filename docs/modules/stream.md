---
title: Stream
description: Resilient per-camera RTSP reader with auto-reconnection
---

# Stream

One thread per camera. The frame never stops flowing.

---

## Global Configuration

Set **before any `VideoCapture` is created** — these are process-wide FFmpeg options:

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

| Option | Purpose |
|--------|---------|
| `rtsp_transport;tcp` | Force TCP for RTSP. UDP drops packets on congested networks. TCP is reliable. |
| `fflags;nobuffer` | Disable FFmpeg's internal buffering. Frames arrive as fast as possible. |
| `flags;low_delay` | Minimize decode latency. Trades quality for speed — appropriate for surveillance. |
| `analyzeduration;1000000` | 1 second to analyze the stream format. Prevents hanging on slow handshakes. |
| `probesize;1000000` | 1 MB probe size. Enough to detect stream metadata without reading the whole file. |
| `stimeout;5000000` | 5-second socket timeout. If no data arrives in 5s, the connection is dead. |

### Thread Stack Size

```python
threading.stack_size(512 * 1024)  # 512 KB
```

Default Python thread stack is **8 MB**. At 20 cameras, that's 160 MB of stack alone. Reducing to 512 KB saves ~150 MB with zero impact — stream reader threads use trivial stack depth. **Must be called before any threads are spawned.**

---

## RTSPStream

```python
class RTSPStream:
    """Reads a single RTSP stream in a dedicated thread with automatic reconnection."""

    _MAX_CONSECUTIVE_FAILURES = 30
    _BASE_RECONNECT_DELAY = 1.0
    _MAX_RECONNECT_DELAY = 60.0
```

### Constructor

```python
def __init__(self, camera: CameraConfig) -> None:
```

**Starts the daemon thread immediately.** No separate `start()` call. By the time the constructor returns, frames may already be flowing.

| Attribute | Type | Purpose |
|-----------|------|---------|
| `camera` | `CameraConfig` | Camera configuration reference |
| `_frame` | `np.ndarray \| None` | Latest decoded frame |
| `_has_frame` | `bool` | Whether any frame has been received |
| `_lock` | `threading.Lock` | Protects `_frame` and `_has_frame` |
| `_stopped` | `threading.Event` | Signal to shut down the reader |
| `_consecutive_failures` | `int` | Reconnection attempt counter (drives backoff) |
| `_connected` | `bool` | Whether the stream is currently live |
| `_thread` | `threading.Thread` | Daemon thread, named `f"stream-{camera.id}"` |

### API

#### `is_connected → bool`

Property. Whether the stream is currently connected and producing frames. Read-only.

#### `latest_frame() → tuple[bool, np.ndarray | None]`

```python
def latest_frame(self) -> tuple[bool, np.ndarray | None]:
```

Returns `(True, frame_copy)` or `(False, None)`.

**Critical detail: returns `frame.copy()`.** Without the copy, the caller would hold a reference to the same numpy array the reader thread is actively overwriting. Race condition. The copy is cheap relative to the cost of face detection.

#### `stop()`

```python
def stop(self) -> None:
```

Sets `_stopped` event. The reader thread checks this on every iteration and exits cleanly. No forced termination, no cleanup headaches.

---

## Internal Methods

### `_run()`

Main loop of the reader thread:

```
while not stopped:
    connect → if fail, reconnect_wait → continue
    read_loop(cap)
    cap.release()
```

### `_connect() → cv2.VideoCapture | None`

Opens the RTSP stream with `cv2.VideoCapture(url, cv2.CAP_FFMPEG)`.

- **Success**: sets `_connected = True`, resets `_consecutive_failures` to 0, returns the `VideoCapture`.
- **Failure**: releases the capture, sets `_connected = False`, returns `None`.

### `_read_loop(cap) → None`

Continuous `cap.read()` loop. Each successful read stores the frame under `_lock`.

**Failure counting**: consecutive failures increment a counter. At **30 consecutive failures**, the loop exits, triggering reconnection. The `_connected` flag goes `False`.

Why 30? A single dropped frame is normal. Ten in a row means the stream is degraded. Thirty means the connection is dead but hasn't timed out yet.

### `_reconnect_wait() → None`

Exponential backoff formula:

```
delay = min(BASE_DELAY × 2^min(attempt, 6), MAX_DELAY)
     = min(1.0 × 2^min(attempt, 6), 60.0)
```

| Attempt | Delay |
|---------|-------|
| 1 | 2.0s |
| 2 | 4.0s |
| 3 | 8.0s |
| 4 | 16.0s |
| 5 | 32.0s |
| 6+ | 60.0s (capped) |

Uses `self._stopped.wait(timeout=delay)` instead of `time.sleep()`. This means `stop()` **immediately interrupts** the wait — no waiting for the full backoff to expire during shutdown.

---

## Thread Safety Model

```
Reader Thread                    Main Thread
─────────────                    ───────────
cap.read()
  ↓
_lock.acquire()
  _frame = frame
  _has_frame = True
_lock.release()
                                stream.latest_frame()
                                  _lock.acquire()
                                    return _frame.copy()
                                  _lock.release()
                                  ↓
                                detector.detect(frame_copy)
```

The lock window is minimal — just a reference assignment and a bool flip. Contention is negligible.
