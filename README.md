```
     _
    / \   _ __ __ _ _   _ ___
   / _ \ | '__/ _` | | | / __|
  / ___ \| | | (_| | |_| \__ \
 /_/   \_\_|  \__, |\__,_|___/
              |___/
  All-Seeing Surveillance System
```

> *"There won't always be a Batman to save you,*
> *but an Oracle will be there to watch you."*

[Documentation](./docs/index.md) — rendered with **MkDocs Material** at [argus docs](https://notoriousarnav.github.io/argus/). To preview locally:

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-red.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)

---

## What is Argus?

Named after **Argus Panoptes** — the hundred-eyed giant of Greek mythology, the perfect watchman who never slept and saw everything — Argus is a multi-camera RTSP surveillance system with real-time face recognition.

Argus connects to RTSP camera streams — including those carelessly left exposed on the open internet — and watches. Every frame is scanned for faces. Every face is compared against a database of targets. The moment it finds someone, it logs the event, saves an annotated screenshot with bounding boxes and confidence scores, and fires webhook notifications to the operator. All of this happens in real time, across multiple cameras simultaneously.

It runs headless on a server with no screen, no keyboard, no human in the loop. When a stream drops, it reconnects automatically with exponential backoff. It doesn't crash, it doesn't give up, and it doesn't forget a face. You tell Argus who to look for, point it at the cameras, and walk away. It handles the rest.

Pair it with Shodan, search engine scrapers, and masscan to discover thousands of exposed RTSP streams across the internet, and Argus becomes something much larger than a home security system. It becomes a distributed, silent observer — watching through cameras that their owners forgot to secure.

---

## Features

- **Multi-camera RTSP ingestion** with resilient auto-reconnection — it doesn't give up
- **Real-time face detection and recognition** using HOG + 128-dimensional dlib encodings
- **Target database** with multiple reference images per person for higher accuracy
- **Per-(target, camera) cooldown** to prevent alert floods without missing new sightings
- **Annotated screenshot capture** on every match — bounding box, name, confidence
- **Webhook notifications** — fire-and-forget in daemon threads, never blocks the eyes
- **Structured JSON logging** with daily rotation and 30-day retention
- **Optional live GUI** with bounding box overlays (see what Argus sees)
- **Headless mode** for silent, unattended deployment on servers and VMs
- **Thread-safe, low-memory footprint** — 512KB stack per stream thread, serialized dlib access

---

## The Pipeline

```
 Shodan / Masscan / Scrapers          Exposed RTSP Streams
 (companion repo)             ───►    on the open internet
                                              │
                                              ▼
                                    ┌───────────────────┐
                                    │    Argus (this)    │
                                    └─────────┬─────────┘
                                              │
            ┌─────────────────────────────────┼─────────────────────────────────┐
            ▼                                 ▼                                 ▼
   ┌─────────────────┐             ┌─────────────────┐             ┌─────────────────┐
   │   RTSPStream    │             │   RTSPStream    │             │   RTSPStream    │
   │   (cam_01)      │             │   (cam_02)      │             │   (cam_N)       │
   └────────┬────────┘             └────────┬────────┘             └────────┬────────┘
            └───────────────────────────────┼───────────────────────────────┘
                                            ▼
                                 ┌──────────────────────┐
                                 │     FaceDetector      │
                                 │  HOG → Encode → Match │
                                 └──────────┬───────────┘
                                            ▼
                                 ┌──────────────────────┐
                                 │     AlertHandler      │
                                 │  Log · Screenshot ·   │
                                 │  Webhook              │
                                 └──────────────────────┘
```

---

## Quick Start

### Prerequisites

- **Python 3.12+**
- System dependencies for `dlib` / `face_recognition`:
  ```bash
  # Debian/Ubuntu
  sudo apt install cmake libboost-all-dev libdlib-dev

  # macOS
  brew install cmake boost dlib
  ```

### Install

```bash
git clone https://github.com/<your-org>/argus.git
cd argus
uv sync
```

### Add a Target

Create a directory under `targets/` for each person Argus should look for:

```
targets/
  john_doe/
    info.json
    front.jpg
    side.jpg
    another_angle.jpg
```

The `info.json` file maps a display name to the reference images:

```json
{
  "name": "John Doe",
  "images": ["front.jpg", "side.jpg", "another_angle.jpg"]
}
```

**Tips for better recognition:**
- Use multiple images (3-6) with varied angles and lighting
- Ensure one clear face per image — if multiple faces are present, only the first is used
- Higher resolution reference images produce better encodings

### Configure Cameras

Edit `config/cameras.toml`:

```toml
[settings]
detection_interval = 0.5    # seconds between detection passes
tolerance = 0.6             # face distance threshold (lower = stricter)
frame_scale = 0.25          # downscale factor (0.25 = 4x reduction)
screenshot_dir = "screenshots"
log_dir = "logs"
cooldown = 10               # seconds before re-alerting same person on same camera

[cameras.cam_01]
name = "Front Door"
url = "rtsp://192.168.1.100:554/stream"

[cameras.cam_02]
name = "Parking Lot"
url = "rtsp://192.168.1.101:554/stream"
```

### Configure Webhooks (Optional)

Edit `config/webhooks.toml`:

```toml
[webhooks.my_server]
enabled = true
url = "http://127.0.0.1:8000/webhook"
method = "POST"
headers = { "Content-Type" = "application/json" }
body_template = '{"person": "{name}", "camera": "{camera}", "confidence": {confidence}, "timestamp": "{timestamp}", "screenshot": "{screenshot}"}'
```

### Run

```bash
# Headless — silent, unattended. The way it was meant to run.
python main.py

# GUI — see what Argus sees. One window per camera.
python main.py --gui

# Custom paths
python main.py --config /path/to/config --targets /path/to/targets
```

---

## Configuration Reference

### Settings — `cameras.toml → [settings]`

| Field | Type | Default | Description |
|---|---|---|---|
| `detection_interval` | `float` | `0.5` | Seconds between detection passes per camera |
| `tolerance` | `float` | `0.6` | Face distance threshold — lower is stricter (0.0–1.0) |
| `frame_scale` | `float` | `0.25` | Downscale factor before detection (0.25 = 4x reduction, faster) |
| `screenshot_dir` | `string` | `"screenshots"` | Output directory for annotated match screenshots |
| `log_dir` | `string` | `"logs"` | Output directory for structured JSON detection logs |
| `cooldown` | `int` | `10` | Seconds before re-alerting the same person on the same camera |

### Cameras — `cameras.toml → [cameras.<id>]`

| Field | Required | Description |
|---|---|---|
| `name` | No | Human-readable camera name (defaults to the camera ID) |
| `url` | **Yes** | RTSP stream URL |

### Webhooks — `webhooks.toml → [webhooks.<id>]`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `true` | Whether this webhook is active |
| `url` | `string` | `""` | Target URL — webhook is skipped if empty |
| `method` | `string` | `"POST"` | HTTP method |
| `headers` | `table` | `{}` | Additional HTTP headers |
| `body_template` | `string` | `""` | JSON body with placeholders (see below) |

**Available placeholders for `body_template`:**

| Placeholder | Description |
|---|---|
| `{name}` | Matched target's name |
| `{camera}` | Camera name |
| `{camera_id}` | Camera ID |
| `{confidence}` | Match confidence (0.0–1.0, higher = better) |
| `{timestamp}` | ISO 8601 timestamp (UTC) |
| `{screenshot}` | File path to the saved annotated screenshot |

### Targets — `targets/<name>/info.json`

```json
{
  "name": "Display Name",
  "images": ["img1.jpg", "img2.jpg", "img3.jpg"]
}
```

All image paths are relative to the target's directory.

---

## CLI Reference

```
python main.py [--gui] [--config PATH] [--targets PATH]
```

| Flag | Default | Description |
|---|---|---|
| `--gui` | Off | Enable live OpenCV display windows (one per camera) |
| `--config` | `config/` | Path to configuration directory containing `.toml` files |
| `--targets` | `targets/` | Path to targets directory containing face reference data |

---

## Companion Tools

Argus watches. But first, someone has to find the streams to watch.

A companion repository contains Shodan API scrapers, search engine dorking tools, and masscan scripts designed to discover RTSP streams exposed on the public internet — cameras with default credentials, no authentication, or misconfigured firewalls. Feed those stream URLs into Argus, and every one of those cameras becomes another pair of eyes.

**Link will be added soon.**

---

## Disclaimer

This project is open-sourced under the **GNU General Public License v3.0** for a specific reason: **so that people can study it, understand the threat, and develop countermeasures.**

The uncomfortable truth is that there are tens of thousands of RTSP camera streams exposed on the public internet right now — with default credentials, no authentication, and no encryption. If your camera is accessible, someone could already be doing exactly what Argus does. The only difference is you wouldn't know about it.

This project exists to make that threat tangible.

**If you operate RTSP cameras, secure them:**

- **Change default credentials** — `admin:admin` is not a password
- **Disable UPnP** — it punches holes in your firewall without asking
- **Firewall RTSP ports** (554, 8554) — block inbound access from the internet
- **Use a VPN** for remote camera access — never expose streams directly
- **Audit your network** — run the companion tools against your own infrastructure before someone else does

The authors assume no responsibility for misuse. This is a security research and awareness tool. What you do with it is on you.

---

## Credits

Argus was built by:

- **Arnav Ghosh**
- **Abhishek Sha**
- **Pratima Mishra**
- **Mandira Singha**

Four pairs of eyes that built a hundred more.

---

## License

This project is licensed under the **GNU General Public License v3.0**.

You are free to use, modify, and redistribute this software under the terms of the GPL-3.0.
Any derivative work must also be released under the same license — ensuring that countermeasures
and improvements remain open and accessible to everyone.

See [LICENSE](LICENSE) for the full license text.

---

*Argus is always watching. The question is whether you're watching back.*
