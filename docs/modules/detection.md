---
title: Detection
description: HOG face detection, 128-D encoding, and vectorized matching
---

# Detection

Face recognition at the speed of surveillance. Every frame, every camera, no exceptions.

---

## `_DETECTION_LOCK`

```python
_DETECTION_LOCK = threading.Lock()
```

Module-level. **All** `face_recognition` calls — `face_locations()`, `face_encodings()`, `face_distance()` — are serialized behind this lock.

Why? `face_recognition` wraps dlib, which uses **global singletons** for its HOG detector and face encoder. These are not thread-safe. Two threads calling `face_locations()` simultaneously will corrupt internal state or crash. The lock is coarse-grained but correct. Detection is fast enough that contention doesn't matter.

---

## FaceDetector

```python
class FaceDetector:
    """Detects faces in frames and matches them against known target encodings."""
```

### Constructor

```python
def __init__(
    self,
    all_encodings: np.ndarray | None,
    encoding_names: list[str],
    settings: Settings,
) -> None:
```

| Parameter | Type | Source |
|-----------|------|--------|
| `all_encodings` | `np.ndarray \| None` | `(N, 128)` matrix from `build_encoding_index()`, or `None` if no targets loaded. |
| `encoding_names` | `list[str]` | Parallel list — `encoding_names[i]` is the name for `all_encodings[i]`. |
| `settings` | `Settings` | Extracts `tolerance` and `frame_scale`. |

Internal state:

| Attribute | Type | Purpose |
|-----------|------|---------|
| `_all_encodings` | `np.ndarray \| None` | The encoding matrix |
| `_encoding_names` | `list[str]` | Name mapping |
| `_tolerance` | `float` | From `settings.tolerance` |
| `_frame_scale` | `float` | From `settings.frame_scale` |
| `_has_targets` | `bool` | `True` only if encodings exist and are non-empty |

**No targets loaded**: logs a warning but doesn't crash. Detection will still find faces — it just can't identify them.

---

### `detect()`

```python
def detect(
    self,
    frame: np.ndarray,
    camera_id: str,
    camera_name: str,
) -> list[MatchEvent]:
```

**Full resolution BGR frame in, list of matches out.**

#### Pipeline

```
1. Downscale frame
     small = cv2.resize(frame, (0,0), fx=scale, fy=scale)

2. Convert BGR → RGB
     rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

3. Acquire _DETECTION_LOCK

4. Detect face locations (HOG model)
     face_locations = face_recognition.face_locations(rgb_small, model="hog")

5. Compute face encodings
     face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

6. Release _DETECTION_LOCK

7. For each detected face:
     a. Compute distances to all target encodings
     b. Find best (minimum) distance
     c. If best_distance ≤ tolerance → create MatchEvent
     d. Scale bbox back to original coordinates
```

#### Edge Cases

| Case | Behavior |
|------|----------|
| No targets loaded | Returns `[]` after detection. Logs nothing — warning already fired at init. |
| No faces in frame | Returns `[]`. Normal. |
| Multiple faces in frame | Each is independently matched. Each gets its own `MatchEvent` if it passes tolerance. |
| Multiple encodings per target | The target's encodings are rows in the flat matrix. Each detected face is compared against **all** encodings from **all** targets. Best match wins. |

---

## Face Distance Matching

```python
distances = face_recognition.face_distance(self._all_encodings, encoding)
best_idx = np.argmin(distances)
best_distance = distances[best_idx]
```

This is a **vectorized numpy operation** — computes Euclidean distance between the detected face's 128-D encoding and every row in the `(N, 128)` matrix in one call. No Python loops over targets.

### Confidence Calculation

```python
confidence = round(1.0 - best_distance, 3)
```

`face_recognition` returns distance, not similarity. Distance 0.0 = identical face. Distance 1.0 = completely different.

Argus **inverts** this for the operator: confidence `1.0` = perfect match, `0.0` = no match. The `round(..., 3)` gives three decimal places — sufficient granularity without noise.

### Tolerance Threshold

```python
if best_distance <= self._tolerance:
    # match
```

Default tolerance: `0.6`. In practice:

| Distance | Confidence | Meaning |
|----------|------------|---------|
| 0.0 – 0.4 | 60–100% | Very likely the same person |
| 0.4 – 0.6 | 40–60% | Probably the same person |
| 0.6+ | < 40% | Rejected — below tolerance |

Lower tolerance = fewer false positives, more missed detections. Higher tolerance = more matches, more false alarms.

---

## Bbox Scaling

Detection happens on the downscaled frame (faster). Bounding boxes must be mapped back to original coordinates:

```python
inv_scale = 1.0 / scale

orig_top = int(top * inv_scale)
orig_right = int(right * inv_scale)
orig_bottom = int(bottom * inv_scale)
orig_left = int(left * inv_scale)
```

With `frame_scale = 0.25`, a face at `(50, 200, 150, 100)` in the small frame becomes `(200, 800, 600, 400)` in the original. The `int()` cast truncates — close enough for bounding boxes.

**The `frame` attached to `MatchEvent` is always the original full-resolution frame**, not the downscaled one. Screenshots and display overlays use original coordinates.

---

## dlib's BBox Format

```
(top, right, bottom, left)
   ↑       ↑       ↑      ↑
   y_min   x_max   y_max  x_min
```

This is **not** `(x, y, w, h)`. When passing to OpenCV:

```python
cv2.rectangle(frame, (left, top), (right, bottom), color, thickness)
```

`cv2.rectangle` expects `(x_min, y_min)` → `(x_max, y_max)`, which maps to `(left, top)` → `(right, bottom)`. This is correct — the values line up.
