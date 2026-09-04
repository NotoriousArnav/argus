---
title: Configuration Reference
description: Full reference for cameras.toml and webhooks.toml
---

# Configuration Reference

Argus loads its configuration from TOML files in a single directory. Two files control behavior: `cameras.toml` for cameras and detection settings, `webhooks.toml` for notification endpoints.

**No hot-reload.** Change a config file, restart Argus. Period.

---

## Directory Structure

```
config/
  cameras.toml      # Camera definitions + global settings
  webhooks.toml     # Webhook notification endpoints
```

Default path is `config/`. Override with `--config /path/to/dir`.

---

## cameras.toml

### `[settings]` — Global Detection Settings

All fields are optional. Omitting any field uses the default.

| Field | Type | Default | Valid Range | Description |
|---|---|---|---|---|
| `detection_interval` | `float` | `0.5` | `> 0` | Seconds between face detection passes **per camera**. Lower = more responsive, higher = less CPU. |
| `tolerance` | `float` | `0.6` | `(0, 1]` | `face_recognition` distance threshold. **Lower = stricter matching.** Below 0.4 produces false negatives; above 0.8 produces false positives. |
| `frame_scale` | `float` | `0.25` | `(0, 1]` | Frame downscale factor before detection. `0.25` = 4x reduction = **4x faster** detection at the cost of precision on distant faces. |
| `screenshot_dir` | `string` | `"screenshots"` | — | Output directory for annotated match screenshots. Created automatically if missing. |
| `log_dir` | `string` | `"logs"` | — | Output directory for structured JSON logs (`detections.json`). Created automatically. |
| `cooldown` | `int` | `10` | — | Seconds before re-alerting the **same person on the same camera**. Prevents alert floods. |
| `model_backend` | `string` | `"dlib_hog"` | see below | Face recognition backend: `dlib_hog`, `dlib_cnn`, `insightface`, or `facenet`. |
| `use_gpu` | `bool` | `false` | — | Use GPU acceleration (InsightFace/FaceNet). Ignored by dlib backends. |

**Validation rules** (enforced at load time via `Settings.__post_init__`):

- `frame_scale` must be in `(0, 1]` — zero or negative values crash immediately
- `tolerance` must be in `(0, 1]` — same constraint
- `detection_interval` must be `> 0` — zero or negative values crash immediately
- `model_backend` must be one of `dlib_hog`, `dlib_cnn`, `insightface`, `facenet`
- Invalid values raise `ValueError` and Argus exits with code `1`

**Full example:**

```toml
[settings]
detection_interval = 0.5
tolerance = 0.6
frame_scale = 0.25
screenshot_dir = "screenshots"
log_dir = "logs"
cooldown = 10
model_backend = "dlib_hog"
use_gpu = false
```

!!! note "Backend availability"
    Only `dlib_hog` and `dlib_cnn` ship with the base install. `insightface` requires `pip install "argus[gpu]"`; `facenet` requires `pip install "argus[facenet]"`. Select an unavailable backend and Argus exits with a clear `pip install` hint. See [Detection](modules/detection.md) for the full backend reference.

!!! note "Tolerance is backend-specific"
    `tolerance = 0.6` is tuned for euclidean dlib distances. Cosine backends (`insightface`, `facenet`) need a lower threshold (`~0.3–0.4`).

### `[cameras.<id>]` — Camera Definitions

Each camera is a TOML table under `[cameras]`. The `<id>` is an arbitrary string identifier — it becomes the camera's ID in logs, webhooks, and screenshot filenames.

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `url` | **Yes** | `string` | — | RTSP stream URL. **Missing `url` crashes with `ValueError`.** |
| `name` | No | `string` | `<id>` | Human-readable display name. Falls back to the camera ID if omitted. |

**At least one camera must be defined.** An empty `[cameras]` section raises `ValueError("No cameras defined in cameras.toml")` and Argus exits.

**Multi-camera example:**

```toml
[cameras.front_door]
name = "Front Door"
url = "rtsp://192.168.1.100:554/stream"

[cameras.parking_lot]
name = "Parking Lot"
url = "rtsp://192.168.1.101:554/stream"

[cameras.lobby]
# No name — ID "lobby" is used as display name
url = "rtsp://10.0.0.5:8554/live"
```

---

## webhooks.toml

### `[webhooks.<id>]` — Webhook Endpoints

Each webhook is a TOML table under `[webhooks]`. The `<id>` is an arbitrary identifier used in log messages.

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `enabled` | No | `bool` | `true` | Set to `false` to disable without deleting. |
| `url` | Conditional | `string` | `""` | Target URL. **Required if `enabled = true`.** Enabled webhooks with empty URLs are skipped with a warning. |
| `method` | No | `string` | `"POST"` | HTTP method. Automatically uppercased. |
| `headers` | No | `table` | `{}` | Additional HTTP headers. Merged with `Content-Type: application/json`. |
| `body_template` | No | `string` | `""` | JSON body with `{placeholder}` patterns. See below. |

**Placeholder substitution is regex-based**, not `str.format()`. This avoids conflicts with JSON curly braces. The pattern `\{(\w+)\}` matches `{placeholder}` tokens.

### Placeholder Reference

| Placeholder | Type | Format | Example |
|---|---|---|---|
| `{name}` | `string` | Target display name | `"Arnav Ghosh"` |
| `{camera}` | `string` | Camera display name | `"Front Door"` |
| `{camera_id}` | `string` | Camera identifier | `"front_door"` |
| `{confidence}` | `float` | `0.0`–`1.0`, **unquoted** in JSON | `0.82` |
| `{timestamp}` | `string` | ISO 8601 UTC | `"2025-01-15T14:23:01.123456"` |
| `{screenshot}` | `string` | Absolute file path | `"/home/user/screenshots/2025-01-15_14-23-01_123456_front_door_Arnav_Ghosh.jpg"` |

**Unknown placeholders** raise `KeyError`, which is caught — the webhook is skipped and the error is logged. The other webhooks still fire.

**Slack incoming webhook:**

```toml
[webhooks.slack]
enabled = true
url = "https://hooks.slack.com/services/T.../B.../xxx"
method = "POST"
headers = {}
body_template = '{"text": "Match detected: *{name}* on *{camera}* (confidence: {confidence}) at {timestamp}"}'
```

**Discord webhook:**

```toml
[webhooks.discord]
enabled = true
url = "https://discord.com/api/webhooks/.../..."
method = "POST"
headers = {}
body_template = '{"content": "**{name}** detected on **{camera}** — confidence: {confidence}"}'
```

**Custom REST API:**

```toml
[webhooks.local_api]
enabled = true
url = "http://127.0.0.1:8000/api/v1/alerts"
method = "POST"
headers = { "Authorization" = "Bearer your-token-here" }
body_template = '{"person": "{name}", "camera": "{camera}", "camera_id": "{camera_id}", "confidence": {confidence}, "timestamp": "{timestamp}", "screenshot": "{screenshot}"}'
```

---

## Configuration Loading Behavior

1. Argus looks for `config/cameras.toml` at the path specified by `--config` (default: `config/`)
2. **File not found** → `FileNotFoundError` caught, logged as error, Argus exits with code `1`
3. **Invalid TOML** → `tomllib` raises, caught as `ValueError`, exits with code `1`
4. **Missing `[settings]`** → All defaults apply — no error
5. **Missing `[cameras]` or empty** → `ValueError("No cameras defined")`, exits with code `1`
6. Camera missing `url` field → `ValueError`, exits with code `1`
7. `config/webhooks.toml` not found → **Warning logged, webhooks disabled.** Argus continues without webhooks.
8. Enabled webhook with no URL → **Warning logged, that webhook skipped.** Others continue.
9. After config loads, `AlertHandler` initializes — loguru sinks are reconfigured. Console output switches to the colored `HH:mm:ss` format. Structured JSON logs begin writing to `<log_dir>/detections.json` with daily rotation, 30-day retention, and zip compression.

---

## No Hot-Reload

Argus reads config **once** at startup. There is no file watching, no signal handling for config refresh, no SIGHUP reload. To apply changes:

1. Edit the `.toml` file
2. Stop Argus (`Ctrl+C`)
3. Start Argus again

This is a deliberate design choice. Hot-reload adds complexity and race conditions that have no place in a surveillance system that should be predictable.
