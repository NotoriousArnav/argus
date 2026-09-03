# Targets Management Guide

Argus identifies people by comparing detected faces against a database of pre-computed **face encodings**. Each person you want to track is a **target** — a directory containing reference images and a manifest.

---

## Directory Structure

```
targets/
  <target_id>/
    info.json          # Manifest: display name + image list
    image1.jpg         # Reference photos
    image2.jpg
    ...
```

The `<target_id>` is an arbitrary directory name. It doesn't appear in logs or webhooks — only the `name` field from `info.json` is used for display.

### Example

```
targets/
  arnav/
    info.json
    1.jpeg
    2.jpeg
    3.jpeg
    4.jpeg
    5.jpeg
    6.jpeg
```

---

## info.json Format

```json
{
  "name": "Display Name",
  "images": ["img1.jpg", "img2.jpg", "img3.jpg"]
}
```

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | No | `string` | Display name shown in logs, screenshots, and webhooks. **Defaults to the directory name** if omitted. |
| `images` | Yes | `list[string]` | Filenames of reference images. Paths are **relative to the target's directory**. Empty list → target skipped. |

**Minimal valid `info.json`:**

```json
{"images": ["face.jpg"]}
```

This uses the directory name as the display name.

---

## Image Requirements

### Format

Any format OpenCV can read: **JPEG, PNG, BMP, TIFF, WebP**. JPEG is recommended for smaller file sizes.

### Resolution

Higher resolution = better encoding quality. There's no minimum, but very small images (under 100px) may produce weak encodings. Aim for **at least 300px face width**.

### Face Clarity

Each image should contain **one clear, visible face**. The face should be:
- Well-lit (avoid silhouettes and deep shadows)
- Roughly frontal (±30° is fine, extreme profiles struggle)
- Unobstructed (no sunglasses, no hands covering the face)

### Multiple Faces Per Image

If an image contains multiple faces, **only the first face detected is used**. Argus logs a warning:

```
WARNING | Multiple faces in photo.jpg for target 'John' — using first face
```

This is not an error — the encoding is still generated. But if the wrong face was first, the encoding is garbage. Use single-face images.

### Number of Images

**3–6 images** is the sweet spot. More images = more encodings = better chance of matching under varying conditions (lighting, angle, expression).

- **1 image** — works, but fragile. One bad encoding = missed detections.
- **3–4 images** — good balance of accuracy and startup speed.
- **6+ images** — diminishing returns, but helps with extreme angle/lighting variation.

### Angles and Lighting

Varied conditions improve recognition robustness:

- Frontal face
- Slight left/right turn
- Different lighting (indoor, outdoor, day, night)
- Different expressions (neutral, smiling)

---

## The Encoding Process

When Argus loads a target, each image goes through:

1. **`face_recognition.load_image_file()`** — reads the image via PIL/OpenCV into an RGB numpy array
2. **`face_recognition.face_encodings(image, num_jitters=1)`** — runs HOG face detection, then computes the 128-dimensional dlib encoding vector
3. **First face only** — if multiple faces are detected, only the first encoding is kept

The `num_jitters=1` setting is a speed/accuracy tradeoff. Higher values (10, 20) improve encoding quality but are **significantly slower**. Argus defaults to 1 for fast startup. This is fine for most use cases — the real-world difference is marginal for clear, frontal photos.

### What Is a Face Encoding?

A 128-dimensional numpy array of floating-point numbers. Two encodings of the same person will be close together in this 128-D space (small Euclidean distance). Two different people will be far apart. The `tolerance` setting in `cameras.toml` controls the distance threshold for a match.

---

## Adding a New Target

1. Create a directory under `targets/`:

```bash
mkdir targets/john_doe
```

2. Place reference images in the directory:

```bash
cp ~/photos/john_front.jpg ~/photos/john_side.jpg targets/john_doe/
```

3. Create `info.json`:

```json
{
  "name": "John Doe",
  "images": ["john_front.jpg", "john_side.jpg"]
}
```

4. Restart Argus. The new target appears in the next startup log:

```
INFO  | Target 'John Doe' loaded with 2 encoding(s)
```

That's it. No database migrations, no rebuild commands. Argus loads all targets from disk on startup.

---

## Removing a Target

Delete the directory:

```bash
rm -rf targets/john_doe
```

Restart Argus. The target is gone.

No undo. No soft-delete. The directory is the source of truth.

---

## Modifying a Target

Edit `info.json` (add/remove images, change the display name) or swap image files. Then **restart Argus**.

There is no hot-reload for targets. Argus computes all encodings at startup and keeps them in memory. Changes require a restart to take effect.

---

## What Happens at Startup

```
INFO  | Loading targets from targets/
INFO  | Target 'Arnav Ghosh' loaded with 6 encoding(s)
WARNING | No face detected in bad_photo.jpg for target 'John' — skipping
WARNING | Multiple faces in group.jpg for target 'John' — using first face
INFO  | Target 'John' loaded with 2 encoding(s)
INFO  | Loaded 2 target(s) with 8 total encoding(s)
```

After loading, all encodings are flattened into a single `(N, 128)` numpy matrix via `build_encoding_index()`. This enables **vectorized comparison** — when a face is detected, its encoding is compared against the entire matrix in one numpy operation, not in a Python loop. This keeps matching fast even with many targets.

---

## Troubleshooting

### "No face detected in image.jpg"

The image doesn't contain a face that dlib's HOG detector can find. Causes:
- Face is too small (low resolution)
- Face is obscured or at an extreme angle
- Image is too dark or overexposed
- Image contains a drawing/photo-of-a-photo rather than a real face

**Fix:** Replace the image with a clearer photo.

### "Multiple faces in image.jpg — using first face"

More than one face was found. Only the first is encoded. If the first face isn't your target, the encoding is wrong.

**Fix:** Use images with a single face, or crop to the target's face.

### "Target '...' has no valid face encodings — skipping"

Every image for this target failed encoding (no faces found, or files missing). The entire target is discarded.

**Fix:** Add at least one image with a clear, detectable face.

### "Target '...' has no images listed — skipping"

`info.json` has an empty `images` array or the field is missing entirely.

**Fix:** Add image filenames to the `images` array.

---

## Performance Impact

| Targets | Encodings | Matrix Size | Match Time (approx.) |
|---|---|---|---|
| 1 | 6 | (6, 128) | < 1ms |
| 5 | 30 | (30, 128) | < 1ms |
| 20 | 120 | (120, 128) | ~1ms |
| 100 | 600 | (600, 128) | ~2-3ms |

The numpy vectorization keeps matching fast. Even with 100 targets (600 encodings), the comparison is a single matrix operation. The bottleneck is **detection** (HOG scan), not **recognition** (encoding comparison).

Adding more targets increases startup time (encoding computation) and memory usage (the encoding matrix lives in RAM), but has negligible impact on per-frame detection speed.
