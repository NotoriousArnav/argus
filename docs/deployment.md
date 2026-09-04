---
title: Deployment Guide
description: systemd, Docker, resource requirements, and scaling
---

# Deployment Guide

Argus runs headless. No screen, no keyboard, no human in the loop. This is how you deploy it that way.

---

## Systemd Service (Recommended)

The intended deployment. Argus runs as a background service, restarts on failure, and stays out of your way.

### 1. Create a dedicated user

```bash
sudo useradd -r -s /usr/sbin/nologin argus
```

### 2. Install Argus

```bash
# Clone and install as the argus user
sudo -u argus git clone https://github.com/<your-org>/argus.git /opt/argus
sudo -u argus bash -c "cd /opt/argus && uv sync"
```

### 3. Create the service file

```bash
sudo tee /etc/systemd/system/argus.service << 'EOF'
[Unit]
Description=Argus — Multi-camera RTSP surveillance with face recognition
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=argus
Group=argus
WorkingDirectory=/opt/argus
ExecStart=/opt/argus/.venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/argus/screenshots /opt/argus/logs

[Install]
WantedBy=multi-user.target
EOF
```

### 4. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable argus
sudo systemctl start argus
```

### 5. Check status and logs

```bash
sudo systemctl status argus
sudo journalctl -u argus -f              # live tail
sudo journalctl -u argus --since today   # today's logs
```

---

## Docker (Conceptual)

No Dockerfile exists yet. Here's what it would need.

### Containerization requirements

- **Base image:** Python 3.12 with cmake, libboost, libdlib-dev pre-installed (dlib compiles from source — this is the heavy part)
- **Entrypoint:** `python main.py` (headless, always)
- **No GUI support:** `--gui` is incompatible with containers (no X11/OpenGL)

### Volume mounts

| Container Path | Purpose | Notes |
|---|---|---|
| `/app/config/` | `cameras.toml`, `webhooks.toml` | Mount read-only if possible |
| `/app/targets/` | Face reference images + `info.json` | Mount read-only after initial setup |
| `/app/screenshots/` | Annotated match screenshots | Must be writable — this grows |
| `/app/logs/` | Structured JSON detection logs | Must be writable |

### Network considerations

- **RTSP access:** Containers need network access to camera streams. Use `--network host` for simplicity, or ensure the bridge network can reach the camera subnet.
- **Webhook outbound:** If webhooks target services on the host, use `host.docker.internal` or the host's bridge IP.
- **No inbound ports needed.** Argus only makes outbound connections (RTSP + webhooks).

```bash
docker run -d \
  --name argus \
  --network host \
  -v /opt/argus/config:/app/config:ro \
  -v /opt/argus/targets:/app/targets:ro \
  -v /opt/argus/screenshots:/app/screenshots \
  -v /opt/argus/logs:/app/logs \
  argus:latest
```

---

## Reverse Proxy (Nginx)

Only needed if your webhook receiver runs on the same host and you want to expose it to external services. Argus itself has no HTTP server.

```nginx
server {
    listen 443 ssl;
    server_name argus.example.com;

    ssl_certificate     /etc/ssl/certs/argus.crt;
    ssl_certificate_key /etc/ssl/private/argus.key;

    location /webhook {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Keep the firewall tight. This endpoint receives detection data — don't expose it wider than necessary.

---

## Log Management

### Log structure

Argus uses **loguru** with two sinks:

| Sink | Format | Level | Purpose |
|---|---|---|---|
| stderr | Human-readable, colored | INFO+ | Live monitoring |
| `logs/detections.json` | Structured JSON | INFO+ | Post-analysis, machine parsing |

### Rotation and retention

Configured in `argus/alert.py`:

- **Rotation:** Daily at midnight (`00:00`)
- **Retention:** 30 days
- **Compression:** ZIP

Old log files are automatically removed. No manual cleanup needed.

### Querying logs with jq

```bash
# All matches for a specific target
jq 'select(.person == "John Doe")' logs/detections.json

# All matches on a specific camera
jq 'select(.camera_id == "cam_01")' logs/detections.json

# High-confidence matches only (>90%)
jq 'select(.confidence > 0.9)' logs/detections.json

# Matches in the last hour
jq 'select(.timestamp > (now - 3600) | todate)' logs/detections.json

# Count matches per camera
jq -s 'group_by(.camera_id) | map({camera: .[0].camera_id, count: length})' \
  logs/detections.json

# Extract timestamps and names as CSV
jq -r '[.timestamp, .person, .camera_id, .confidence] | @csv' \
  logs/detections.json
```

---

## Screenshot Management

### File naming convention

```
YYYY-MM-DD_HH-MM-SS_MICROSEC_cameraID_targetName.jpg
```

Example: `2026-09-03_14-23-07_123456_cam_01_John_Doe.jpg`

Each file is annotated with a green bounding box, name label, and confidence score.

### Disk space considerations

- **JPEG quality:** 85% (set in `argus/alert.py`)
- **Typical file size:** 50–200 KB per screenshot depending on resolution
- **At scale:** 10 cameras, 1 person each, cooldown=10s → ~6 screenshots/min → ~360/hour → ~8.6 MB/hour

### Cleanup strategy

```bash
# Delete screenshots older than 7 days
find /opt/argus/screenshots -name "*.jpg" -mtime +7 -delete

# Or use a cron job
0 2 * * * find /opt/argus/screenshots -name "*.jpg" -mtime +7 -delete
```

---

## Resource Requirements

### CPU

Face detection is **CPU-bound**. The dlib HOG model runs on CPU only — no GPU acceleration is supported.

| Component | Impact |
|---|---|
| Frame decoding (FFmpeg/OpenCV) | Low |
| Frame resize (`frame_scale`) | Low |
| HOG face detection | **High** — this is the bottleneck |
| 128-D encoding comparison | Low — vectorized numpy |

Each camera shares the same detection lock (`_DETECTION_LOCK`). More cameras = more contention on that lock.

### RAM

| Component | Memory |
|---|---|
| Thread stack (per camera) | 512 KB (reduced from 8 MB default) |
| Frame buffer (per camera) | ~2–8 MB depending on resolution |
| Target encodings | ~512 bytes per encoding (128 floats × 4 bytes) |
| OpenCV + dlib | ~50–100 MB baseline |

**Rule of thumb:** 10 cameras at 1080p ≈ 200–400 MB total RSS.

### Network

Each RTSP stream pulls continuous bandwidth:

| Resolution | Codec | Bandwidth |
|---|---|---|
| 720p | H.264 | 1–4 Mbps |
| 1080p | H.264 | 2–8 Mbps |
| 4K | H.264 | 10–20 Mbps |

Argus uses TCP transport (`rtsp_transport;tcp` in FFmpeg options) for reliability. UDP would be faster but drops frames silently.

### Storage rotation

| Asset | Growth Rate | Retention |
|---|---|---|
| `logs/detections.json` | Low | 30 days (auto-rotated, zipped) |
| `screenshots/` | High | Manual or cron cleanup |
| Compressed log archives | Low | Auto-deleted after 30 days |

---

## Multi-Camera Scaling

### Per-camera costs

Each camera spawns one `RTSPStream` daemon thread. The thread:
- Holds one `cv2.VideoCapture` handle (FFmpeg demuxer + decoder)
- Maintains one frame buffer under a `threading.Lock`
- Reads frames at stream speed (drains RTSP buffer continuously)

### Detection interval tradeoffs

| `detection_interval` | CPU Load | Miss Rate | Best For |
|---|---|---|---|
| 0.25s | Very high | Lowest | Critical areas, few cameras |
| 0.5s (default) | High | Low | General surveillance |
| 1.0s | Moderate | Moderate | Many cameras, less critical |
| 2.0s | Low | Higher | Background monitoring |

More cameras at the same interval = more lock contention in `_DETECTION_LOCK`. Detection is serialized, not parallelized.

---

## Monitoring Argus

### Process health

```bash
# Is Argus running?
sudo systemctl is-active argus

# Check for crash loops
sudo systemctl status argus | grep -E "Active|Memory|Main PID"
```

### Log-based health checks

```bash
# Check for recent activity (should see detection logs)
journalctl -u argus --since "5 min ago" | grep "MATCH"

# Check for connection issues
journalctl -u argus | grep "Failed to connect"

# Check for reconnection loops
journalctl -u argus | grep "Reconnecting"
```

### External monitoring

If you need heartbeat monitoring, watch the log file's modification time:

```bash
# Alert if no log activity in 5 minutes
find /opt/argus/logs -name "detections.json" -mmin +5
```

Or monitor the systemd unit:

```bash
# Script for external monitoring
systemctl is-active argus >/dev/null 2>&1 || echo "Argus is DOWN"
```

Argus logs `Argus is watching. Press Ctrl+C to stop.` on startup and `Argus stopped. All-seeing eyes closed.` on shutdown. If you see the latter without a restart, something went wrong.
