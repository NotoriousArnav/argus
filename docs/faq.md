---
title: Frequently Asked Questions
description: Common issues and solutions — connectivity, performance, false positives
---

# Frequently Asked Questions

---

## "Argus can't connect to my RTSP stream"

Check these in order:

1. **URL format** — Must be `rtsp://host:port/path`. No trailing slashes, no typos.
2. **Network connectivity** — Can you ping the camera from the Argus server?
   ```bash
   ping 192.168.1.100
   ```
3. **Credentials** — Are the username and password correct? Test manually:
   ```bash
   ffprobe rtsp://user:pass@192.168.1.100:554/stream
   ```
4. **Transport** — Argus uses TCP transport by default (`rtsp_transport;tcp`). Some cameras only support UDP. If you suspect this, test with UDP:
   ```bash
   ffprobe -rtsp_transport udp rtsp://user:pass@192.168.1.100:554/stream
   ```
5. **Firewall** — Is port 554 blocked between the Argus server and the camera? Check with:
   ```bash
   nmap -p554 192.168.1.100
   ```
6. **Port** — Not all cameras use 554. Check your camera's RTSP server port in its web interface. Common alternatives: 8554, 8080, or a custom port.

Argus logs connection failures with `[camera_id] Failed to connect to 'Camera Name'`. Check `journalctl -u argus` or the stderr output.

---

## "Face detection is slow"

Face detection is CPU-bound for the dlib backends. To speed up the **default** setup:

1. **Increase `frame_scale`** — Default is 0.25 (4x reduction). Try 0.1 (10x reduction) for much faster detection at the cost of accuracy on small faces:
   ```toml
   frame_scale = 0.1
   ```

2. **Increase `detection_interval`** — Default is 0.5s. Try 1.0s or 2.0s:
   ```toml
   detection_interval = 1.0
   ```

3. **Fewer targets** — Each detected face is compared against all target encodings. More targets = slower matching. Remove targets you don't actively need.

4. **Hardware** — dlib HOG is single-threaded per detection call. A faster CPU directly improves detection speed.

5. **Go GPU** — If you have an NVIDIA GPU, switch to a CUDA backend and move detection off the CPU entirely:
   ```bash
   pip install "argus[gpu]"
   ```
   ```toml
   [settings]
   model_backend = "insightface"   # or facenet
   use_gpu = true
   ```
   GPU inference is typically an order of magnitude faster and more accurate than CPU HOG.

---

## "No faces detected in my camera"

The HOG detector finds faces under specific conditions:

- **Lighting** — Faces need adequate, even lighting. Backlit or silhouette faces are invisible to HOG.
- **Camera angle** — Front-facing or slightly angled faces work best. Extreme profile views (90°) are often missed.
- **Face size** — If the face is too small in the frame, HOG won't detect it. Solutions:
  - Increase camera resolution
  - Decrease `frame_scale` (e.g., 0.1 or 0.2) to detect smaller faces
  - Move the camera closer to the subject
- **Resolution** — Low-resolution cameras (VGA, CIF) may produce faces too small to detect reliably.

Argus's accuracy is bounded by the detection backend you chose. Want stronger recognition? [Swap the backend](modules/detection.md) — this is a first-class config option now:

| Backend | Accuracy | Cost |
|---|---|---|
| `dlib_hog` (default) | good for clear, frontal faces | CPU, runs anywhere |
| `dlib_cnn` | better on small/blurred/angled | ~10x CPU cost, or a GPU |
| `insightface` | best — SCRFD + ArcFace 512-D | needs `argus[gpu]` + CUDA |
| `facenet` | strong — MTCNN + FaceNet 512-D | needs `argus[facenet]` + CUDA |

```toml
[settings]
model_backend = "insightface"   # or facenet / dlib_cnn
use_gpu = true                  # for the 512-D backends
```

Set `model_backend` in `cameras.toml`, install the matching extra (`pip install "argus[gpu]"`), and Argus uses the new model — no code changes. Remember to re-tune `tolerance` (cosine backends want ~0.3–0.4) and that switching backends rebuilds the target gallery on next startup.

---

## "False positive matches"

Argus matches a detected face against all target encodings and checks if the distance is below `tolerance`. False positives happen when the tolerance is too loose.

1. **Decrease `tolerance`** — Default is 0.6. Try 0.4 or lower for stricter matching:
   ```toml
   tolerance = 0.4
   ```
   Lower tolerance = fewer false positives, but also more missed matches.

2. **More reference images** — Add 3–6 images per target with varied angles, lighting, and expressions. More reference encodings improve the accuracy of the comparison.

3. **Match deployment conditions** — If Argus watches a dark parking lot, don't use bright studio headshots as reference images. Use reference images that approximate the conditions Argus will see.

4. **Check target images** — If an image contains multiple faces, only the first face is used for encoding. Ensure each reference image has one clear face.

---

## "Screenshots directory is filling up fast"

Screenshots accumulate quickly with high match rates and low cooldowns.

1. **Increase cooldown** — Default is 10 seconds. Increase to reduce screenshot frequency:
   ```toml
   cooldown = 60   # One screenshot per target-camera per minute
   ```

2. **Increase detection interval** — Fewer detection passes = fewer matches = fewer screenshots.

3. **Automated cleanup** — Add a cron job:
   ```bash
   # Delete screenshots older than 7 days
   0 2 * * * find /opt/argus/screenshots -name "*.jpg" -mtime +7 -delete
   ```

4. **Disk monitoring** — Set up alerts when the screenshots directory exceeds a size threshold.

---

## "Webhook not firing"

1. **Check configuration:**
   ```toml
   [webhooks.my_server]
   enabled = true          # Must be true
   url = "http://..."      # Must be non-empty
   method = "POST"
   ```

2. **Check logs for errors:**
   ```bash
   journalctl -u argus | grep "Webhook"
   ```
   Common errors: timeout, HTTP 4xx/5xx, connection refused.

3. **Test the endpoint manually:**
   ```bash
   curl -X POST http://127.0.0.1:8000/webhook \
     -H "Content-Type: application/json" \
     -d '{"test": true}'
   ```

4. **Check body template syntax** — Placeholders must use `{name}` format (curly braces, no quotes around values for numbers):
   ```toml
   body_template = '{"person": "{name}", "confidence": {confidence}}'
   ```
   Available placeholders: `{name}`, `{camera}`, `{camera_id}`, `{confidence}`, `{timestamp}`, `{screenshot}`.

5. **Webhook runs in a daemon thread** — Errors are logged but do not crash Argus. Check the logs, not just the webhook receiver.

---

## "How do I add more cameras?"

Add a new `[cameras.<id>]` section to `config/cameras.toml`:

```toml
[cameras.cam_03]
name = "Loading Dock"
url = "rtsp://admin:pass@192.168.1.102:554/stream"
```

Argus will automatically spawn a new `RTSPStream` thread for the camera on next startup. No code changes needed.

**Monitor resources** — Each camera adds:
- One daemon thread (512 KB stack)
- One `cv2.VideoCapture` handle (FFmpeg demuxer)
- One frame buffer (2–8 MB at 1080p)
- More contention on the `_DETECTION_LOCK` (detection is serialized)

Start with 5–10 cameras and scale from there based on CPU and RAM usage.

---

## "Can I run Argus on a Raspberry Pi?"

Yes, with caveats.

- **Face detection will be slow.** The ARM CPU in a Raspberry Pi is significantly slower than x86 for dlib HOG operations. Expect 1–3 seconds per detection pass instead of 0.1–0.5 seconds.
- **Increase `frame_scale`:** Use 0.1 or lower to reduce the pixel count that HOG processes.
- **Increase `detection_interval`:** Use 1.0 or 2.0 seconds to reduce CPU load.
- **Consider fewer cameras:** 1–2 cameras maximum on a Pi 4.
- **Stick with `dlib_hog`.** It's the only backend that runs well on a Pi's CPU. `dlib_cnn`, `insightface`, and `facenet` all need desktop-class hardware or a CUDA GPU — Argus will refuse (with a clear error) if you select them without the installed dependencies, so you can't accidentally cripple a Pi.
- **No GPU acceleration:** dlib's HOG model is CPU-only. The Pi's GPU is not utilized.

For higher performance on ARM, consider a Jetson Nano or similar with CUDA support — Argus's `insightface` / `facenet` backends use CUDA directly (`use_gpu = true`).

---

## "Logs are too verbose"

Two sinks are configured:

| Sink | Level | Purpose |
|---|---|---|
| stderr | INFO+ | Live monitoring — colored, human-readable |
| `logs/detections.json` | INFO+ | Post-analysis — structured, machine-parseable |

The JSON log captures everything at INFO level and above. To reduce console noise, adjust the log level in `argus/alert.py`:

```python
# Console: change INFO to WARNING for less output
logger.add(sys.stderr, level="WARNING", ...)

# JSON file: keep at INFO for full capture
logger.add(str(log_dir / "detections.json"), serialize=True, level="INFO", ...)
```

---

## "How does the cooldown work?"

The cooldown prevents alert spam for the same person on the same camera.

- **Key:** `(target_name, camera_id)` tuple
- **Behavior:** After alerting on a match, Argus waits `cooldown` seconds before alerting again on the **same target and camera**
- **Independence:** Different cameras and different targets have independent cooldowns

| Scenario | Cooldown applies? |
|---|---|
| "John" on cam_01, then "John" on cam_01 (5s later) | Yes — suppressed |
| "John" on cam_01, then "John" on cam_02 (5s later) | No — different camera, alerts on both |
| "John" on cam_01, then "Jane" on cam_01 (5s later) | No — different person, alerts on both |

Set in `config/cameras.toml`:

```toml
[settings]
cooldown = 10  # seconds
```

---

## "Can I use this with NVR/DVR systems?"

Yes. Most NVRs and DVRs expose RTSP streams. The format depends on the manufacturer.

**Common RTSP URL formats:**

| Manufacturer | Typical Format |
|---|---|
| Hikvision | `rtsp://ip:554/Streaming/Channels/101` |
| Dahua | `rtsp://ip:554/cam/realmonitor?channel=1&subtype=0` |
| Generic ONVIF | `rtsp://ip:554/0` or `rtsp://ip:8554/live` |
| Synology Surveillance | `rtsp://ip:554/Sn1/stream1` |

Find the exact URL in your NVR's web interface under **Camera Settings → RTSP** or **Stream Settings**.

---

## "What happens when a camera goes offline?"

Argus handles this automatically through the `RTSPStream` reconnection logic.

1. **Detection:** The reader thread detects consecutive read failures (30 in a row)
2. **Disconnect:** The stream marks itself as disconnected
3. **Backoff:** Exponential backoff begins — delays double each attempt:
   - 1s → 2s → 4s → 8s → 16s → 32s → 60s (capped)
4. **Reconnect:** When the camera comes back online, the stream resumes immediately
5. **No manual intervention:** Argus does not crash, does not require restart

Logs show:
```
[cam_01] 30 consecutive read failures — reconnecting
[cam_01] Reconnecting in 2.0s (attempt 2)
[cam_01] Failed to connect to 'Front Door'
[cam_01] Reconnecting in 4.0s (attempt 3)
[cam_01] Connected to 'Front Door'
```

The `_stopped` event can interrupt the backoff wait, so `SIGTERM` shutdown is not blocked by a reconnecting camera.
