# Configuration

Two TOML files. One function each. Fail loud, fail fast.

---

## Constants

```python
DEFAULT_CONFIG_DIR = Path("config")
```

Used as the default argument for both `load_cameras_config()` and `load_webhooks_config()`. Overridden via `--config` CLI flag.

---

## TOML Parsing

Argus uses **`tomllib`** from the Python 3.11+ stdlib. No third-party TOML library. Files are opened in binary mode (`"rb"`) as required by `tomllib`.

---

## `load_cameras_config()`

```python
def load_cameras_config(
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> tuple[Settings, list[CameraConfig]]:
```

### Behavior

1. Resolves `{config_dir}/cameras.toml`.
2. Checks existence — raises `FileNotFoundError` if missing.
3. Parses TOML into a raw dict.
4. Extracts `[settings]` section, fills defaults for missing keys.
5. Constructs `Settings()` — **`__post_init__` fires here**, raising `ValueError` on invalid ranges.
6. Extracts `[cameras]` section. Raises `ValueError` if empty.
7. For each camera: requires `url` field, fills `name` from config or defaults to the key.
8. Returns `(settings, list[CameraConfig])`.

### Error Cases

| Condition | Exception | When |
|-----------|-----------|------|
| `cameras.toml` missing | `FileNotFoundError` | Path doesn't exist |
| Empty `[cameras]` section | `ValueError("No cameras defined in cameras.toml")` | TOML parses but no camera entries |
| Missing `url` field | `ValueError("Camera '{id}' is missing required 'url' field")` | Camera entry has no `url` |
| Invalid `frame_scale` | `ValueError("frame_scale must be in (0, 1], ...")` | `Settings.__post_init__` |
| Invalid `tolerance` | `ValueError("tolerance must be in (0, 1], ...")` | `Settings.__post_init__` |
| Invalid `detection_interval` | `ValueError("detection_interval must be > 0, ...")` | `Settings.__post_init__` |

All exceptions propagate to `main.py`, which catches `(FileNotFoundError, ValueError)` and calls `sys.exit(1)`.

### Example `cameras.toml`

```toml
[settings]
detection_interval = 0.5
tolerance = 0.6
frame_scale = 0.25

[cameras.cam_01]
name = "Front Door"
url = "rtsp://192.168.1.100:554/stream"

[cameras.cam_02]
url = "rtsp://192.168.1.101:554/stream"  # name defaults to "cam_02"
```

---

## `load_webhooks_config()`

```python
def load_webhooks_config(config_dir: Path = DEFAULT_CONFIG_DIR) -> list[WebhookConfig]:
```

### Behavior

1. Resolves `{config_dir}/webhooks.toml`.
2. If missing — **logs a warning and returns `[]`**. Does not crash. Webhooks are optional.
3. Parses TOML.
4. For each entry under `[webhooks]`: constructs `WebhookConfig`, uppercases `method`.
5. **Filtering logic**: only includes webhooks where `enabled == True` **and** `url` is non-empty.
6. Enabled webhooks with empty URLs get a warning log and are skipped.

### Filtering Truth Table

| `enabled` | `url` | Result |
|-----------|-------|--------|
| `True` | non-empty | **Included** |
| `True` | `""` | Skipped + warning |
| `False` | anything | Silently skipped |

### Example `webhooks.toml`

```toml
[webhooks.my_server]
enabled = true
url = "http://127.0.0.1:8000/webhook"
method = "POST"
headers = { "X-Api-Key" = "secret" }
body_template = '{"person": "{name}", "camera": "{camera}", "confidence": {confidence}}'
```

---

## The Validation Chain

```
TOML file
  → tomllib.load()          (raw dict)
  → Settings(...)            (constructs dataclass)
    → __post_init__()        (validates ranges)
  → ValueError               (propagates up)
  → main.py catches          (exits with code 1)
```

The validation is **eager and terminal**. Argus does not guess, default silently, or attempt recovery. If your config is wrong, it tells you exactly what and exits.
