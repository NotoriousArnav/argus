---
title: Webhooks
description: Template system, placeholders, HTTP behavior, and service examples
---

# Webhooks

## How It Works

When Argus matches a face, the `AlertHandler` does three things in order:

1. **Checks cooldown** — if this exact `(target, camera)` pair was alerted within `cooldown` seconds, the event is silently dropped
2. **Saves a screenshot** — annotated JPEG with bounding box, name, and confidence score
3. **Fires webhooks** — one daemon thread per enabled webhook, per match event

Webhooks are **fire-and-forget**. They never block detection. If a webhook times out or returns an error, it's logged and Argus moves on. No retries. No queuing. No circuit breakers. The eyes don't stop to wait for the messenger.

```
Match Event
    │
    ▼
AlertHandler.handle()
    │
    ├──► Cooldown check (per target+camera pair)
    │
    ├──► Save screenshot (annotated JPEG)
    │
    ├──► Structured log entry (JSON, daily rotation)
    │
    └──► For each enabled webhook:
           └──► daemon thread → _send_webhook()
                  ├── Substitute {placeholders} via regex
                  ├── POST/PUT/etc. to configured URL
                  └── Log success or failure
```

---

## Template System

`body_template` uses **regex substitution** (`re.sub` with pattern `\{(\w+)\}`), not Python's `str.format()`.

**Why?** JSON bodies are full of curly braces. `str.format()` would choke on `{"key": "value"}` — it would try to interpret JSON structure as placeholder syntax. Regex substitution only touches explicit `{placeholder}` tokens.

### Placeholder Reference

| Placeholder | Type | JSON Quoted? | Source | Example Value |
|---|---|---|---|---|
| `{name}` | `string` | Yes | Target display name | `"Arnav Ghosh"` |
| `{camera}` | `string` | Yes | Camera display name | `"Front Door"` |
| `{camera_id}` | `string` | Yes | Camera identifier | `"front_door"` |
| `{confidence}` | `float` | **No** | `0.0`–`1.0` | `0.82` |
| `{timestamp}` | `string` | Yes | ISO 8601 UTC | `"2025-01-15T14:23:01.123456"` |
| `{screenshot}` | `string` | Yes | Absolute file path | `"/home/user/screenshots/..."` |

**Key detail:** `{confidence}` is **not quoted** in the output. This is intentional — it produces valid JSON numeric values:

```json
{"confidence": 0.82}
```

Not:

```json
{"confidence": "0.82"}
```

### Unknown Placeholders

If `body_template` contains `{something}` and `something` is not in the replacement map, a `KeyError` is caught. That specific webhook is **skipped entirely** — the error is logged, and other webhooks still fire normally.

```
ERROR | Webhook 'slack' body_template error: unknown placeholder 'location'
```

---

## HTTP Details

| Parameter | Value |
|---|---|
| **Method** | Configurable (`method` field). Default: `POST`. Automatically uppercased. |
| **Headers** | User-defined `headers` table merged with `Content-Type: application/json` (which is always added). |
| **Timeout** | **10 seconds**, hardcoded. |
| **TLS verification** | Uses httpx defaults (verification enabled). Not configurable. |
| **Body encoding** | Raw bytes (`content=body`), not form data. |
| **Concurrency** | One daemon thread per webhook per match event. Non-blocking. |

### Error Handling

| Error | Log Level | Message | Behavior |
|---|---|---|---|
| Timeout | `WARNING` | `Webhook '...' timed out` | Skipped, no retry |
| HTTP 4xx/5xx | `ERROR` | `Webhook '...' HTTP error: 404` | Skipped, no retry |
| Connection/DNS | `ERROR` | `Webhook '...' request error: ...` | Skipped, no retry |
| Unknown placeholder | `ERROR` | `Webhook '...' body_template error: unknown placeholder '...'` | Webhook skipped |

**No retry logic.** If the endpoint is down, the alert is lost. This is a surveillance system, not a message queue. If you need guaranteed delivery, put a queue (n8n, Celery, etc.) in front of the webhook endpoint.

---

## Examples

### Slack Incoming Webhook

```toml
[webhooks.slack]
enabled = true
url = "https://hooks.slack.com/services/YOUR-WORKSPACE/YOUR-CHANNEL/YOUR-SECRET-TOKEN"
method = "POST"
body_template = '{"text": ":rotating_light: *{name}* detected on *{camera}* (confidence: {confidence}) at {timestamp}"}'
```

### Discord Webhook

```toml
[webhooks.discord]
enabled = true
url = "https://discord.com/api/webhooks/YOUR-WEBHOOK-ID/YOUR-WEBHOOK-TOKEN"
method = "POST"
body_template = '{"content": ":warning: **{name}** seen on **{camera}** — confidence {confidence}"}'
```

### Custom REST API

```toml
[webhooks.internal_api]
enabled = true
url = "https://api.example.com/v1/surveillance/alerts"
method = "POST"
headers = { "Authorization" = "Bearer eyJhbGciOiJIUzI1NiIs..." }
body_template = '{"person": "{name}", "cam": "{camera_id}", "conf": {confidence}, "ts": "{timestamp}", "img": "{screenshot}"}'
```

### n8n / Zapier Integration

```toml
[webhooks.n8n]
enabled = true
url = "https://your-n8n-instance.com/webhook/abc123"
method = "POST"
body_template = '{"event": "face_match", "target": "{name}", "source": "{camera}", "confidence": {confidence}, "captured_at": "{timestamp}", "evidence": "{screenshot}"}'
```

### Disabled Webhook (Keep Config, Stop Firing)

```toml
[webhooks.old_endpoint]
enabled = false
url = "http://legacy-server:9000/alerts"
method = "POST"
body_template = '{"name": "{name}"}'
```

---

## Performance

- **Daemon threads** — every webhook call runs in a `threading.Thread(daemon=True)`. Detection never blocks.
- **One thread per webhook per match** — if you have 3 webhooks and a match occurs, 3 threads spawn simultaneously.
- **No thread pool or queue** — threads are spawned directly. For typical deployments (1-5 webhooks), this is fine. For high-volume setups, put a reverse proxy or queue in front.
- **httpx** handles connection pooling internally, but each thread creates its own request.

---

## Security Considerations

- **No TLS verification config** — httpx defaults apply (verification enabled). Self-signed certs will fail.
- **No auth token management** — if your endpoint needs authentication, put it in the `headers` table manually.
- **Credentials in plaintext** — API keys and bearer tokens in `webhooks.toml` are stored as plain text. Secure the file with filesystem permissions.
- **No IP allowlisting** — Argus doesn't filter outbound connections by destination.
- **Fire-and-forget** — no delivery guarantee. If you need auditability, log the webhook responses on the receiving end.
