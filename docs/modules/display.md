---
title: Display
description: GUI windows, detection overlays, and main-thread constraint
---

# Display

See what Argus sees. One window per camera. Optional — headless doesn't need it.

---

## Constraint

**All `cv2.imshow()` and `cv2.waitKey()` calls MUST happen on the main thread.**

This is not a suggestion. OpenCV's highGUI backend (Qt, Cocoa, GTK) requires it. Call from a background thread and you get a crash, a hang, or silent corruption. The `StreamManager` enforces this by calling `Display.update()` and `Display.tick()` from the main thread only.

---

## Display

```python
class Display:
    """Renders one OpenCV window per camera with detection overlays."""
```

### Constructor

```python
def __init__(self, cameras: list[CameraConfig]) -> None:
```

Creates **one window per camera**:

```python
window_name = f"Argus — {cam.name} [{cam.id}]"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
cv2.resizeWindow(window_name, 640, 480)
```

| Detail | Value |
|--------|-------|
| Window flag | `WINDOW_NORMAL` — resizable by the user |
| Initial size | 640 × 480 |
| Naming | `"Argus — Front Door [cam_01]"` |

Internal state:

| Attribute | Type | Purpose |
|-----------|------|---------|
| `_cameras` | `dict[str, CameraConfig]` | Camera ID → config |
| `_window_names` | `dict[str, str]` | Camera ID → window name string |

---

### `update()`

```python
def update(
    self,
    camera_id: str,
    frame: np.ndarray,
    detections: list[MatchEvent] | None = None,
) -> None:
```

**Called once per camera per detection cycle** from the main thread.

1. Copies the frame (never modifies the original).
2. If detections exist, draws overlays for each.
3. Calls `cv2.imshow(window_name, display_frame)`.

If `camera_id` doesn't match any known window, returns silently.

---

### `_draw_detection()`

```python
@staticmethod
def _draw_detection(frame: np.ndarray, event: MatchEvent) -> None:
```

Draws on the frame **in-place**. Modifies the copy, not the original.

#### Drawing Steps

```
1. Green bounding box (2px)
     cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

2. Compute label text size
     label = "John Doe (87%)"
     label_size = cv2.getTextSize(label, FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]

3. Green filled rectangle above the bbox (label background)
     cv2.rectangle(frame,
         (left, top - label_size[1] - 10),
         (left + label_size[0] + 4, top),
         (0, 255, 0), cv2.FILLED)

4. Black text on green background
     cv2.putText(frame, label, (left + 2, top - 5),
         FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
```

Label format: `"{target_name} ({confidence:.0%})"` → `"John Doe (87%)"`.

**Color scheme**: green box, green label background, black text. High contrast on any scene. The same drawing logic exists in `AlertHandler._save_screenshot()` — duplicated intentionally for independence.

---

### `tick()`

```python
@staticmethod
def tick() -> bool:
```

```python
key = cv2.waitKey(1) & 0xFF
return key != ord("q")
```

| Return | Meaning |
|--------|---------|
| `True` | Keep running |
| `False` | User pressed `q` — shutdown requested |

`cv2.waitKey(1)` waits 1ms for a key event and processes all pending GUI events (window redraws, resize, focus changes). Without this call, windows freeze.

The `& 0xFF` mask is necessary on some platforms where `waitKey` returns modifier key bits.

---

### `destroy()`

```python
@staticmethod
def destroy() -> None:
```

```python
cv2.destroyAllWindows()
```

Closes every OpenCV window. Called from `_shutdown()` after all streams are stopped.

---

## Window Management

| Operation | Thread | Timing |
|-----------|--------|--------|
| `namedWindow` / `resizeWindow` | Main (constructor) | Once at startup |
| `imshow` | Main (update) | Every detection cycle per camera |
| `waitKey` | Main (tick) | Every main loop iteration |
| `destroyAllWindows` | Main (shutdown) | Once at teardown |

All GUI operations are confined to the main thread. No locks needed — there's only one writer.
