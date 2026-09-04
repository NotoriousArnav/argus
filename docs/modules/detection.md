---
title: Detection
description: Dispatcher + pluggable backends — dlib HOG/CNN, InsightFace, FaceNet
---

# Detection

Face recognition at the speed of surveillance. Every frame, every camera, no exceptions.

Argus no longer hard-codes a single face model. Detection is a **dispatcher**: it reads which backend is configured, resolves it, and exposes it through one uniform call. Swap the model, change nothing else.

---

## The Dispatcher

`argus/detection.py` is deliberately thin. It does only one job: **decide which backend to use from config, and hand it to the pipeline.**

`FaceDetector` is a *variable*, not a class — it holds whichever backend `Settings.model_backend` selects.

```python
# argus/detection.py
def resolve_backend(settings, use_gpu=None) -> Backend: ...
def FaceDetector(all_encodings, encoding_names, settings, use_gpu=None) -> Backend: ...
```

`resolve_backend()` reads `settings.model_backend` and `settings.use_gpu`, validates the backend and its dependencies, loads its pre-trained models, and returns a ready instance. `FaceDetector()` is a convenience wrapper that also attaches the target gallery.

The rest of Argus — `manager.py`, `alert.py`, `display.py` — calls `detector.detect(...)` identically no matter which model is running. **Changing the model changes zero lines of pipeline code.**

---

## The Backends

Each backend lives in `argus/detection_models/`, self-contained and independently installable. All implement the same `Backend` contract:

| Backend | Detector | Encoder | Dim | Metric | GPU | Install |
|---|---|---|---|---|---|---|
| `dlib_hog` | dlib HOG | dlib ResNet | 128 | euclidean | no | base |
| `dlib_cnn` | dlib CNN | dlib ResNet | 128 | euclidean | advised | base |
| `insightface` | SCRFD | ArcFace/ResNet100 | 512 | cosine | yes | `argus[gpu]` |
| `facenet` | MTCNN | InceptionResnetV1 | 512 | cosine | yes | `argus[facenet]` |

### The Contract

```python
class Backend(ABC):
    name: str          # config-identifiable
    dim: int           # embedding dimension (128 or 512)
    metric: str        # "euclidean" or "cosine"

    def is_available(self) -> bool     # deps installed?
    def build(self) -> None            # load pre-trained models
    def set_gallery(self, gallery, names) -> None
    def encode_image(self, image) -> list[np.ndarray]   # target encoding
    def detect(self, frame, camera_id, camera_name) -> list[MatchEvent]
    def distance(self, gallery, encoding) -> np.ndarray  # similarity
```

### `argus/detection_models/__init__.py`

- **`Backend`** — the abstract contract, shared matching logic, and `ndarray_from_file()`.
- **`register(name)`** — decorator that drops a backend class into the `_REGISTRY`.
- **`get_backend(name, settings, use_gpu)`** — factory: validates the name, checks `is_available()`, calls `build()`, returns the instance.
- **`available_backends()`** — sorted list of registered names, shown in dispatch errors.

### `dlib_based.py` — the default

Wraps the `face_recognition` library verbatim. **This is the original Argus behavior, preserved exactly** — the no-regression path. Two registered variants share one implementation:

- `dlib_hog` — HOG detector. CPU-only, light, runs anywhere Python does, including a Raspberry Pi.
- `dlib_cnn` — CNN detector. Handles small, blurred, and angled faces far better, but needs a GPU or many CPU cores. **Same 128-D encodings and euclidean metric as `dlib_hog`, so the same target gallery works for both.**

### `insightface_model.py` — beefy hardware, best accuracy

The `buffalo_l` pack: **SCRFD detector** (tiny/occluded faces) + **ArcFace / ResNet100** encoder (512-D). Runs on CUDA via `onnxruntime-gpu`. This is the high-accuracy tier.

### `facenet_model.py` — the FaceNet family

**MTCNN detector** (robust to pose/lighting) + **InceptionResnetV1** encoder (512-D). Runs on CUDA via PyTorch. A solid alternative to InsightFace.

---

## The Lock

```python
_DETECTION_LOCK = threading.Lock()   # dlib_based
_INFERENCE_LOCK = threading.Lock()   # insightface / facenet
```

Every backend serializes inference behind its own module-level lock. Why? `face_recognition`/dlib use global singletons that are not thread-safe, and CUDA contexts are likewise not safe to run concurrently across threads. The lock is coarse-grained but correct — inference is fast enough that contention doesn't matter.

---

## The Live Pipeline (`detect`)

Regardless of backend, every `detect()` follows the same shape:

```
1. Downscale frame          small = resize(frame, fx=scale, fy=scale)
2. Convert BGR → RGB        rgb_small = cvtColor(small, BGR2RGB)
3. Acquire inference lock
4. Detect faces             (HOG / CNN / SCRFD / MTCNN)
5. Compute encodings        (128-D or 512-D)
6. Release lock
7. For each face:
     a. Compute distances to all gallery rows
     b. Find best (minimum) distance
     c. If best_distance ≤ tolerance → MatchEvent
     d. Scale bbox back to original coordinates
```

The shared `_match()` helper (in `Backend`) builds the `MatchEvent`s. Backends only override `distance()`; the matching, bbox scaling, and confidence math are identical.

---

## Matching & Confidence

### Euclidean backends (dlib)

```python
distances = face_distance(gallery, encoding)   # L2 distance
best_distance = min(distances)
```

### Cosine backends (InsightFace, FaceNet)

```python
cos_sim = gallery @ encoding                    # rows are normalized
distances = clip(1.0 - cos_sim, 0.0, 1.0)       # cosine distance
```

Both are minimized — lower is a better match. Confidence is always:

```python
confidence = round(1.0 - best_distance, 3)
```

**Semantics differ, so tune `tolerance` per backend.** Euclidean dlib distances run 0–1 with a sensible default of `0.6`; cosine distances for the same-vs-different threshold land around `0.4`. The default `0.6` is a dlib-euclidean value — if you switch to a cosine backend, expect to lower it.

| Backend | Typical tolerance | Notes |
|---|---|---|
| `dlib_hog` | `0.6` | original default |
| `dlib_cnn` | `0.6` | same embeddings as HOG |
| `insightface` | `0.3–0.4` | cosine distance |
| `facenet` | `0.3–0.4` | cosine distance |

---

## Bbox Scaling

Detection runs on the downscaled frame. Boxes map back to original coordinates:

```python
orig_top, orig_right, orig_bottom, orig_left = (
    int(top * inv_scale), int(right * inv_scale),
    int(bottom * inv_scale), int(left * inv_scale),
)
```

**The `frame` attached to `MatchEvent` is always the full-resolution original**, not the downscaled one. Screenshots and display overlays use original coordinates.

For InsightFace/FaceNet, SCRFD/MTCNN return `(x1, y1, x2, y2)`; each backend converts to Argus's canonical `(top, right, bottom, left)` before matching.

---

## Config

```toml
[settings]
model_backend = "dlib_hog"    # dlib_hog | dlib_cnn | insightface | facenet
use_gpu = false
```

Override with the runtime flag (`python main.py` reads these from `cameras.toml`). Missing-extra backends fail loudly with the exact `pip install` command, never silently.

---

## Edge Cases

| Case | Behavior |
|------|----------|
| No targets loaded | `detect` returns `[]` after detection; a warning fires at startup |
| No faces in frame | Returns `[]` — normal |
| Multiple faces | Each independently matched, each gets its own `MatchEvent` if within tolerance |
| Backend deps missing | `resolve_backend` raises a clear `ValueError` with the install command |
| Unknown `model_backend` | `Settings` validation rejects it with the valid list |
