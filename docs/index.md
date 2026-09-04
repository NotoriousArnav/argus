---
title: Argus
description: Multi-camera RTSP surveillance with real-time face recognition — the all-seeing system
---
# Argus

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

![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-red.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)

---

**Argus** is a multi-camera RTSP surveillance system with real-time face recognition. Named after **Argus Panoptes** — the hundred-eyed giant of Greek mythology who never slept — it connects to RTSP camera streams on the open internet, scans every frame for faces, matches them against a database of targets, logs the event, captures annotated screenshots, and fires webhook notifications. All of it happens in real time, across multiple cameras simultaneously, with no human in the loop.

It doesn't crash. It doesn't give up. And it doesn't forget a face.

---

## Features

- **Multi-camera RTSP ingestion** with resilient auto-reconnection and exponential backoff
- **Real-time face detection and recognition** — HOG detector + 128-dimensional dlib encodings
- **Target database** with multiple reference images per person for higher accuracy
- **Per-(target, camera) cooldown** to prevent alert floods without missing new sightings
- **Annotated screenshot capture** on every match — bounding box, name, confidence score
- **Webhook notifications** — fire-and-forget in daemon threads, never blocks the eyes
- **Structured JSON logging** with daily rotation and 30-day retention
- **Optional live GUI** with bounding box overlays — see what Argus sees
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

Each camera runs in its own thread, draining the RTSP buffer as fast as frames arrive. The main thread consumes frames at a configurable detection interval, runs face recognition, and dispatches matches. Webhooks fire in separate daemon threads. **The pipeline is the watchman.**

---

## Documentation

### Core

| Document | Description |
|---|---|
| [Getting Started](getting-started.md) | Installation, configuration, first run, and verification |
| [Architecture](architecture.md) | Threading model, data flow, synchronization, and design decisions |
| [Configuration](configuration.md) | Full reference for `cameras.toml` and `webhooks.toml` |
| [CLI Reference](cli-reference.md) | Command-line flags, usage examples, exit behavior |

### Modules

| Document | Description |
|---|---|
| [Module Overview](modules/overview.md) | Dependency graph, responsibilities, thread ownership |
| [Models](modules/models.md) | Data classes — `CameraConfig`, `Settings`, `MatchEvent`, and more |
| [Config Loading](modules/config.md) | TOML parsing, validation chain, error handling |
| [RTSP Stream](modules/stream.md) | Per-camera threading, reconnection, FFmpeg options |
| [Face Detection](modules/detection.md) | HOG detection, 128-D encoding, vectorized matching |
| [Alert Handler](modules/alert.md) | Cooldowns, screenshots, webhooks, loguru sinks |
| [Stream Manager](modules/manager.md) | Orchestration, main loop, signal handling |
| [Display](modules/display.md) | GUI windows, detection overlays, main-thread constraint |
| [Targets](modules/targets.md) | Target loading, encoding computation, index building |

### Guides

| Document | Description |
|---|---|
| [Webhooks](webhooks.md) | Template system, placeholders, HTTP behavior, service examples |
| [Targets Guide](targets-guide.md) | Adding targets, image requirements, encoding process, troubleshooting |

### Operations

| Document | Description |
|---|---|
| [Deployment](deployment.md) | systemd, Docker, resource requirements, scaling |
| [Security](security.md) | Camera hardening, deployment security, **why GPL-3.0**, privacy, ethical use |
| [Contributing](contributing.md) | Code style, architecture decisions, development setup |
| [FAQ](faq.md) | Common issues and solutions — connectivity, performance, false positives |

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

This project is licensed under the **GNU General Public License v3.0**. Not MIT. Not Apache. GPL.

For a surveillance tool, permissive licenses are dangerous. MIT or Apache would allow someone to fork Argus, strip the security warnings, close the source, and sell it as a proprietary monitoring product — erasing the research intent while preserving the surveillance capability.

GPL-3.0 ensures that:

- **Source code is always available.** Anyone can examine exactly how Argus watches, what it logs, and where it sends data. No black boxes.
- **Derivative works stay open.** Forks must carry the same license. The security research mandate propagates.
- **Anti-tivoization.** Argus can't be embedded in locked-down hardware that prevents owners from auditing the surveillance software running on their own devices.
- **Patent protection.** Contributors grant patent rights. No patent ambushes.
- **Shadow-users are protected.** The people being watched never consented to surveillance. GPL-3.0 guarantees they can study the tool being used against them — something impossible with proprietary software.

See [LICENSE](https://github.com/NotoriousArnav/argus/blob/master/LICENSE) for the full license text. See [Security — Why GPL-3.0](security.md#why-gpl-30-and-not-mit-or-apache) for the full rationale.

---

*Argus is always watching. The question is whether you're watching back.*
