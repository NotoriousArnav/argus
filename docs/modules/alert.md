# Alert

Match found. Log it. Screenshot it. Notify. Move on.

---

## AlertHandler

```python
class AlertHandler:
    """Handles face match events: structured logging, screenshots, and webhooks.
    Enforces a per-(target, camera) cooldown to avoid alert spam.
    Webhook calls are fire-and-forget in daemon threads to never block detection."""
```

### Constructor

```python
def __init__(
    self,
    settings: Settings,
    webhooks: list[WebhookConfig],
) -> None:
```

| Action | Detail |
|--------|--------|
| Creates `screenshots/` dir | `Path(settings.screenshot_dir).mkdir(parents=True, exist_ok=True)` |
| Creates `logs/` dir | `Path(settings.log_dir).mkdir(parents=True, exist_ok=True)` |
| Initializes cooldown dict | `_cooldowns: dict[tuple[str, str], float]` — keys are `(target_name, camera_id)` |
| Initializes cooldown lock | `_cooldown_lock: threading.Lock` |
| Calls `_setup_logging()` | Reconfigures loguru globally |

---

## Logging Setup

```python
def _setup_logging(self, log_dir: Path) -> None:
```

**Two sinks. Both fire on every log call.**

### Sink 1: Colored Console (stderr)

```python
logger.add(
    sys.stderr,
    level="INFO",
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level:<8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
        "{message}"
    ),
)
```

Time format: `HH:mm:ss` — **24-hour, no date**. Operator doesn't need the date in terminal output. The JSON file has full timestamps.

### Sink 2: Structured JSON File

```python
logger.add(
    str(log_dir / "detections.json"),
    serialize=True,
    rotation="00:00",
    retention="30 days",
    compression="zip",
    level="INFO",
)
```

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `serialize` | `True` | Each log entry is a JSON object with structured fields |
| `rotation` | `"00:00"` | New file every midnight |
| `retention` | `"30 days"` | Auto-delete after 30 days |
| `compression` | `"zip"` | Old files compressed on rotation |

**`logger.remove()` is called first** — this nukes loguru's default handler to prevent duplicate console output.

---

## `handle()`

```python
def handle(self, event: MatchEvent) -> None:
```

**The main entry point.** Called by `StreamManager` for every match event.

### Flow

```
1. Check cooldown → if active, return immediately
2. Update cooldown timestamp
3. Save annotated screenshot
4. Log the match (success level)
5. Fire webhooks (non-blocking)
```

---

## Cooldown System

```python
_cooldowns: dict[tuple[str, str], float]  # (target_name, camera_id) → monotonic timestamp
_cooldown_lock: threading.Lock
```

### How It Works

- Key: `(target_name, camera_id)` — each person on each camera has its own cooldown.
- Value: `time.monotonic()` timestamp of last alert.
- Check: `(time.monotonic() - last_alert) < settings.cooldown` → still on cooldown.

**Why `time.monotonic()`?** Wall clock time (`time.time()`) can jump — NTP sync, DST, manual adjustment. Monotonic time never goes backwards. A cooldown window is always exactly the configured duration.

**Why per-(target, camera)?** If "John" is seen on cam_01, we alert once and cool down for 10 seconds on cam_01. But if "John" appears on cam_02 during that window, that's a **separate sighting** and gets its own alert.

### Thread Safety

`_cooldown_lock` protects the dict. Even though the main loop is single-threaded today, the lock exists for correctness if concurrent `handle()` calls ever happen.

---

## `_save_screenshot()`

```python
def _save_screenshot(self, event: MatchEvent) -> Path:
```

### Filename Format

```
{timestamp}_{camera_id}_{target_name}.jpg
```

Example: `2025-01-15_14-30-22_123456_cam_01_John Doe.jpg`

Timestamp uses `%Y-%m-%d_%H-%M-%S_%f` — microsecond precision to avoid collisions.

### Annotation Drawing

1. Copies the frame (never modifies the original).
2. Draws a **green bounding box** (2px thickness) at the bbox coordinates.
3. Draws a **green filled rectangle** for the label background.
4. Draws **black text** on the green background: `"John Doe (87%)"`.
5. Writes as JPEG with **quality 85** — good enough for evidence, small enough for storage.

### Edge Case

If `event.frame is None` (shouldn't happen in normal operation), logs a warning and returns the path anyway. No crash.

---

## Webhook Dispatch

### `_fire_webhooks()

```python
def _fire_webhooks(self, event: MatchEvent, screenshot_path: str) -> None:
```

Spawns **one daemon thread per webhook**. Fire-and-forget — if a webhook fails, detection continues unaffected.

### `_send_webhook()`

```python
@staticmethod
def _send_webhook(
    webhook: WebhookConfig,
    event: MatchEvent,
    screenshot_path: str,
) -> None:
```

#### Template Substitution

Uses **regex**, not `str.format()`:

```python
body = re.sub(r"\{(\w+)\}", _replace, webhook.body_template)
```

Why? `str.format()` conflicts with JSON. Your `body_template` is a JSON string with `{}` braces everywhere. `str.format()` tries to interpret JSON structure as Python placeholders. Regex avoids this entirely.

Available placeholders:

| Placeholder | Value |
|-------------|-------|
| `{name}` | `event.target_name` |
| `{camera}` | `event.camera_name` |
| `{camera_id}` | `event.camera_id` |
| `{confidence}` | `event.confidence` (numeric, unquoted) |
| `{timestamp}` | `event.timestamp.isoformat()` |
| `{screenshot}` | Screenshot file path |

Numbers are **not quoted** in the substitution — `confidence` renders as `0.873`, not `"0.873"`. This preserves valid JSON when the template has numeric values.

Unknown placeholders raise `KeyError` — logged as an error, webhook skipped.

#### HTTP Request

```python
resp = httpx.request(
    method=webhook.method,
    url=webhook.url,
    content=body,
    headers=headers,
    timeout=10.0,
)
resp.raise_for_status()
```

| Error Type | Handling |
|------------|----------|
| `httpx.TimeoutException` | Logged as warning. No retry. |
| `httpx.HTTPStatusError` | Logged as error with status code. No retry. |
| `httpx.RequestError` | Logged as error. No retry. |

**10-second timeout.** A webhook that takes longer than 10 seconds is a broken webhook. No retries — the next match will try again.
