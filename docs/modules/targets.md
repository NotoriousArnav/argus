---
title: Targets
description: Target loading, encoding computation, and index building
---

# Targets

Point Argus at a face. It never forgets it.

---

## Directory Structure

```
targets/
  john_doe/
    info.json
    front.jpg
    side.jpg
    another_angle.jpg
  jane_smith/
    info.json
    headshot.jpg
```

Each subdirectory is one target. The directory name is the fallback identifier if `info.json` is missing a `name` field.

### `info.json` Format

```json
{
  "name": "John Doe",
  "images": ["front.jpg", "side.jpg", "another_angle.jpg"]
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `name` | No | Display name. Falls back to directory name. |
| `images` | **Yes** | List of filenames relative to the target's directory. Empty = target skipped. |

---

## `load_targets()`

```python
DEFAULT_TARGETS_DIR = Path("targets")

def load_targets(targets_dir: Path = DEFAULT_TARGETS_DIR, backend: Backend | None = None) -> list[Target]:
```

`backend` is the active face backend. It's injected so **target encodings are computed with the same model that runs live detection** — see [matching correctness](#matching-correctness) below.

### Flow

```
1. Check targets_dir exists
   → If missing: warn, return []

2. Iterate sorted subdirectories (skips non-directories)

3. For each subdirectory:
   a. Check for info.json
      → If missing: warn, skip
   b. Call _load_single_target()
      → Returns Target or None

4. Collect non-None targets

5. Log summary: N targets, M total encodings
```

**Sorted iteration** — deterministic target loading order. No dependence on filesystem ordering.

### Error Cases

| Condition | Behavior |
|-----------|----------|
| `targets/` doesn't exist | Warning log, returns `[]`. Not fatal. |
| No `info.json` in subdirectory | Warning log, skips that subdirectory. |
| Corrupt JSON | Error log, skips that target. |
| No images listed | Warning log, skips that target. |
| Image file missing | Warning log, continues with remaining images. |
| No face in any image | Error log, skips that target entirely. |

A target with **zero valid encodings** never reaches the detector.

---

## `_load_single_target()`

```python
def _load_single_target(target_path: Path, info_path: Path) -> Target | None:
```

1. Reads and parses `info.json`.
2. Extracts `name` (defaults to directory name).
3. Iterates image files — calls `_compute_encoding()` for each.
4. Collects successful encodings.
5. Returns `Target(name, encodings)` or `None` if zero encodings.

### JSON Error Handling

```python
try:
    with open(info_path) as f:
        info = json.load(f)
except (json.JSONDecodeError, OSError) as e:
    logger.error("Failed to read {}: {}", info_path, e)
    return None
```

Catches both corrupt JSON and filesystem errors (permission denied, etc.).

---

## `_compute_encoding()`

```python
def _compute_encoding(img_path: Path, target_name: str, backend: Backend) -> np.ndarray | None:
```

### Pipeline

```python
image = backend.ndarray_from_file(str(img_path))   # BGR ndarray
face_encs = backend.encode_image(image)            # matching encoder
```

1. Load image as an ndarray via `backend.ndarray_from_file()` (OpenCV under the hood, cross-format).
2. Detect faces and compute encodings with `backend.encode_image()` — the **same encoder** used at runtime.
3. Return the first encoding, or `None` if no face found.

### `num_jitters=1`

This controls how many times the face is re-sampled before computing the encoding. Higher = more robust encoding, slower processing.

| Value | Speed | Accuracy |
|-------|-------|----------|
| 1 | Fast | Good enough for surveillance |
| 10 | 10× slower | Marginally better |
| 100 | 100× slower | Diminishing returns |

**`1` is the correct choice for target loading.** You're pre-computing encodings once, but you may have dozens of images across multiple targets. The accuracy gain from higher jitters doesn't justify the startup time.

### Multiple Faces

```python
if len(face_encs) > 1:
    logger.warning(
        "Multiple faces in {} for target '{}' — using first face",
        img_path, target_name,
    )
```

**First-face-only policy.** `face_encodings()` without an `encoding` parameter detects all faces and encodes all of them, but the code only takes `[0]`. If your reference photo has two people, only the first detected face is used. This is intentional — you should be providing solo photos for targets.

---

## `build_encoding_index()`

```python
def build_encoding_index(
    targets: list[Target],
) -> tuple[np.ndarray | None, list[str]]:
```

Flattens all targets' encodings into a single matrix for vectorized comparison.

### Returns

| Value | Type | Detail |
|-------|------|--------|
| `all_encodings` | `np.ndarray \| None` | `(N, 128)` matrix. `None` if no targets. |
| `encoding_names` | `list[str]` | `encoding_names[i]` = name for `all_encodings[i]`. |

### Example

```
Target "John Doe"  → 3 encodings
Target "Jane Smith" → 2 encodings

all_encodings:  shape (5, 128)
encoding_names: ["John Doe", "John Doe", "John Doe", "Jane Smith", "Jane Smith"]
```

This flat structure enables a single `face_recognition.face_distance()` call to compare a detected face against **every target encoding in one vectorized operation**. No Python loops over targets.

### Empty Case

```python
if not targets:
    return None, []
```

Returns `None` for the matrix and an empty list. The detector handles this gracefully — it still finds faces but can't identify anyone.

---

## Matching Correctness

**Target encodings must be computed with the same backend that runs live detection.** This is why `backend` is threaded through `load_targets()`, `_load_single_target()`, and `_compute_encoding()`.

Why it matters: a 128-D dlib euclidean encoding and a 512-D InsightFace cosine encoding live in **different vector spaces**. You can't compare them. If you build the gallery with `dlib_hog` but detect with `insightface`, every match fails or, worse, produces garbage. Argus wires the same backend through both paths automatically — `main.py` resolves the backend first, hands it to `load_targets(backend=...)`, and calls `backend.set_gallery(...)` before detection starts.

Switching backends invalidates your target gallery. Re-run Argus after `pip install "argus[gpu]"` + `model_backend = "insightface"` and it recomputes the encodings on next startup.

---

## Encoding Lifecycle

```
Startup:
  resolve_backend(settings)      → Backend (matches config)
  load_targets(backend=backend)  → list[Target] (each with list[np.ndarray])
  build_encoding_index()         → (N,128) matrix + names list
  backend.set_gallery(matrix, names)

Runtime:
  backend.detect()               → face_distance(matrix, encoding)
                                   → argmin → best_idx → names[best_idx] → MatchEvent
```

Encodings are computed **once** at startup and held in memory for the lifetime of the process. They're small — dlib's are 128 float64 values = 1 KB each; 512-D cosine backends are 4 KB each. A hundred targets with 5 images each is still under a megabyte. Negligible.
