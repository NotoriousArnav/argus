---
title: Getting Started
description: Installation, configuration, first run, and verification
---

# Getting Started

> *Point it at the cameras and walk away. It handles the rest.*

![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-red.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)

---

## Prerequisites

**Python 3.12 or newer.** No exceptions. Argus uses modern type syntax that older versions won't parse.

**System dependencies** for `dlib` and `face_recognition`. These are C++ libraries — they need a compiler and Boost:

```bash
# Debian / Ubuntu (apt)
sudo apt install cmake libboost-all-dev libdlib-dev

# Fedora / RHEL / Rocky / Alma (dnf)
sudo dnf install cmake boost-devel dlib-devel

# Arch / Manjaro (pacman)
sudo pacman -S cmake boost dlib

# Void (xbps)
sudo xbps-install cmake boost-devel dlib-devel

# Gentoo (emerge)
sudo emerge --ask dev-libs/boost dev-libs/dlib dev-util/cmake

# macOS (Homebrew)
brew install cmake boost dlib
```

You'll also need `uv` — the Python package manager Argus uses:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Installation

```bash
git clone https://github.com/<your-org>/argus.git
cd argus
uv sync
```

`uv sync` installs all dependencies into a virtual environment and links the `argus` entry point. The entire dependency tree — OpenCV, dlib, face_recognition, httpx, loguru — resolves in one pass.

---

## Adding Your First Target

Argus identifies people by comparing camera frames against a database of pre-computed face encodings. Each target lives in its own directory under `targets/`.

### Directory Structure

```
targets/
  john_doe/
    info.json
    front.jpg
    side.jpg
    another_angle.jpg
```

### info.json Format

```json
{
  "name": "John Doe",
  "images": ["front.jpg", "side.jpg", "another_angle.jpg"]
}
```

| Field | Type | Description |
|---|---|---|
| `name` | `string` | Display name — appears in logs, screenshots, and webhooks |
| `images` | `list[string]` | Image filenames relative to the target's directory |

### Tips for Better Recognition

- **Use 3–6 images** with varied angles, expressions, and lighting conditions.
- **One clear face per image.** If multiple faces are present, only the first is used.
- **Higher resolution is better.** Tiny, blurry faces produce poor encodings.
- **Front-facing is the baseline.** Add profile views and different lighting for robustness.
- **JPEG or PNG** — both work. Avoid heavily compressed images.

### Adding More Targets

Just create another directory:

```
targets/
  john_doe/
    info.json
    *.jpg
  jane_smith/
    info.json
    *.jpg
```

Argus scans `targets/` on startup, computes 128-D encodings for every image, and builds a flat index. The more targets, the more comparisons per frame — but the vectorized matching is fast.

---

## Configuring Cameras

Edit `config/cameras.toml`. This file defines both global settings and individual camera streams.

### Settings

```toml
[settings]
detection_interval = 0.5    # seconds between detection passes per camera
tolerance = 0.6             # face distance threshold (lower = stricter)
frame_scale = 0.25          # downscale factor (0.25 = 4x reduction)
screenshot_dir = "screenshots"
log_dir = "logs"
cooldown = 10               # seconds before re-alerting same person on same camera
```

| Field | Type | Default | What It Does |
|---|---|---|---|
| `detection_interval` | `float` | `0.5` | How often each camera is scanned. Lower = more responsive, higher = less CPU. |
| `tolerance` | `float` | `0.6` | Face distance threshold. `0.0` = perfect match only, `1.0` = match everything. `0.5–0.6` is the sweet spot. |
| `frame_scale` | `float` | `0.25` | Downscale factor before detection. `0.25` means the frame is shrunk to 1/4 width and height (1/16 the pixels). Faster detection, minor accuracy trade-off. |
| `screenshot_dir` | `string` | `"screenshots"` | Where annotated match screenshots are saved. |
| `log_dir` | `string` | `"logs"` | Where structured JSON detection logs are written. |
| `cooldown` | `int` | `10` | Per-(target, camera) cooldown in seconds. Prevents the same person on the same camera from generating 100 alerts per second. |

### Cameras

```toml
[cameras.cam_01]
name = "Front Door"
url = "rtsp://192.168.1.100:554/stream"

[cameras.cam_02]
name = "Parking Lot"
url = "rtsp://192.168.1.101:554/stream"
```

| Field | Required | Description |
|---|---|---|
| `name` | No | Human-readable name. Defaults to the camera ID if omitted. |
| `url` | **Yes** | Full RTSP stream URL. Argus opens this with FFmpeg over TCP. |

Add as many cameras as you want. Each one gets its own daemon thread with a 512KB stack. Twenty cameras? Sixty-four megabytes of stack memory total. Argus is built for scale.

---

## Configuring Webhooks

Edit `config/webhooks.toml`. Webhooks fire on every face match, after cooldown filtering.

```toml
[webhooks.my_server]
enabled = true
url = "http://127.0.0.1:8000/webhook"
method = "POST"
headers = { "Content-Type" = "application/json" }
body_template = '{"person": "{name}", "camera": "{camera}", "confidence": {confidence}, "timestamp": "{timestamp}", "screenshot": "{screenshot}"}'
```

### Available Placeholders

| Placeholder | Value | Type |
|---|---|---|
| `{name}` | Matched target's display name | `string` |
| `{camera}` | Camera name | `string` |
| `{camera_id}` | Camera ID (the TOML key) | `string` |
| `{confidence}` | Match confidence (0.0–1.0) | `number` |
| `{timestamp}` | ISO 8601 UTC timestamp | `string` |
| `{screenshot}` | File path to saved annotated screenshot | `string` |

Numbers are injected unquoted. Strings are injected as-is. The template is regex-substituted — not `str.format()` — so curly braces in your JSON don't conflict with placeholder syntax.

### Webhook Behavior

- **Fire-and-forget.** Each webhook fires in a dedicated daemon thread. A slow or dead endpoint never blocks detection.
- **10-second timeout.** If the endpoint doesn't respond, the webhook fails silently with a log warning.
- **Multiple webhooks.** Define as many as you need. All enabled webhooks fire on every match.

---

## Running Argus

```bash
# Headless — silent, unattended. The way it was meant to run.
uv run python main.py

# GUI — see what Argus sees. One window per camera.
uv run python main.py --gui

# Custom paths — point at your own config and targets
uv run python main.py --config /path/to/config --targets /path/to/targets
```

### CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--gui` | Off | Enable live OpenCV display windows (one per camera, must run on main thread) |
| `--config` | `config/` | Path to configuration directory containing `.toml` files |
| `--targets` | `targets/` | Path to targets directory containing face reference data |

### What to Expect

When Argus starts, you'll see the banner and a series of log lines:

```
     _
    / \   _ __ __ _ _   _ ___
   / _ \ | '__/ _` | | | / __|
  / ___ \| | | (_| | |_| \__ \
 /_/   \_\_|  \__, |\__,_|___/
              |___/
  All-Seeing Surveillance System

14:32:01 | INFO     | argus.config:load_cameras_config | Loaded 4 camera(s) from config/cameras.toml
14:32:01 | INFO     | argus.alert:_setup_logging | ...
14:32:01 | INFO     | argus | Configuration loaded: 4 camera(s), 1 webhook(s)
14:32:01 | INFO     | argus | Loading targets from targets/
14:32:02 | INFO     | argus.targets:_load_single_target | Target 'Arnav' loaded with 6 encoding(s)
14:32:02 | INFO     | argus | Starting Argus: 4 camera(s), 1 target(s), 1 webhook(s)
14:32:02 | INFO     | argus | Starting 4 camera stream(s)...
14:32:02 | INFO     | argus | Argus is watching. Press Ctrl+C to stop.
14:32:02 | INFO     | argus.stream:stream-0 | Starting stream reader for Webcam
14:32:02 | INFO     | argus.stream:stream-0 | Connected to 'Webcam'
```

When a match occurs:

```
14:35:12 | SUCCESS  | argus.alert:handle | MATCH: 'Arnav' on 'Webcam' (confidence: 92.3%)
```

A green bounding box screenshot is saved to `screenshots/`, and the webhook fires.

---

## Verification

1. **Check that cameras connect.** Look for `Connected to '<name>'` log lines. If you see `Failed to connect`, verify the RTSP URL is reachable (`ffplay <url>` is a quick test).

2. **Check that targets loaded.** The log line `Target '<name>' loaded with N encoding(s)` confirms face encodings were computed. Zero encodings means the images didn't contain detectable faces — use clearer photos.

3. **Check webhooks.** Add a simple test server:
   ```bash
   python -m http.server 8000
   ```
   Then set your webhook URL to `http://127.0.0.1:8000/webhook`. Watch the terminal — you'll see the POST request land when Argus detects a face.

4. **Check screenshots.** After a match, look in `screenshots/`. You should see a JPEG with a green bounding box, name label, and confidence score drawn on the frame.

5. **Check logs.** The structured JSON log at `logs/detections.json` records every match event with metadata. Rotate daily, retain 30 days, compress to zip.

6. **Press Ctrl+C.** Argus shuts down cleanly:
   ```
   14:40:00 | INFO     | argus.manager:_signal_handler | Received signal 2, shutting down...
   14:40:00 | INFO     | argus.manager:_shutdown | Shutting down Argus...
   14:40:00 | INFO     | argus.manager:_shutdown | Argus stopped. All-seeing eyes closed.
   ```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `dlib` fails to install | Make sure `cmake` and Boost are installed (see [Prerequisites](#prerequisites)). On Debian: `sudo apt install cmake libboost-all-dev libdlib-dev`. On Fedora: `sudo dnf install cmake boost-devel dlib-devel`. On Arch: `sudo pacman -S cmake boost dlib`. |
| No faces detected in target images | Use higher-resolution, well-lit photos with a single clear face. |
| Camera won't connect | Verify the RTSP URL with `ffplay <url>`. Check credentials, port, and firewall rules. |
| High CPU usage | Increase `frame_scale` (e.g., `0.15`) or `detection_interval` (e.g., `1.0`). |
| `ModuleNotFoundError: No module named 'cv2'` | Run `uv sync` again. Make sure you're using `uv run python`, not bare `python`. |

---

*Argus is always watching. The question is whether you're watching back.*
