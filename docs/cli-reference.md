# CLI Reference

## Program

**`argus`** — installed as a console script via `pyproject.toml` (`[project.scripts] argus = "main:main"`).

If running from source without installing:

```
python main.py [OPTIONS]
```

## Usage

```
argus [--gui] [--config PATH] [--targets PATH]
```

```
python main.py [--gui] [--config PATH] [--targets PATH]
```

## Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--gui` | `bool` (store_true) | `false` | Enable live OpenCV display windows — one per camera. Each window shows the stream with bounding box overlays on detected faces. |
| `--config` | `Path` | `config/` | Path to the configuration directory containing `cameras.toml` and `webhooks.toml`. |
| `--targets` | `Path` | `targets/` | Path to the targets directory containing face reference data. |

All flags are optional. Running bare `argus` or `python main.py` starts in headless mode with default paths.

## Examples

**Headless mode — silent, unattended. The default.**

```bash
argus
```

**GUI mode — see what Argus sees. One window per camera.**

```bash
argus --gui
```

**Custom config and targets paths:**

```bash
argus --config /etc/argus/config --targets /etc/argus/targets
```

**Running from outside the project directory:**

```bash
cd /opt && argus --config /home/user/argus/config --targets /home/user/argus/targets
```

**Using the installed console script after `uv sync`:**

```bash
argus --gui
```

**Direct Python invocation:**

```bash
python /home/user/argus/main.py --gui
```

## Startup Output

On launch, Argus prints the ASCII banner to stderr, then loads components in order:

```
     _
    / \   _ __ __ _ _   _ ___
   / _ \ | '__/ _` | | | / __|
  / ___ \| | | (_| | |_| \__ \
 /_/   \_\_|  \__, |\__,_|___/
              |___/
  All-Seeing Surveillance System
```

Followed by log output:

- `Loaded N camera(s) from config/cameras.toml` — camera count
- `Webhook '...' loaded: https://...` — per-webhook load confirmation
- `Configuration loaded: N camera(s), N webhook(s)` — summary
- `Loading targets from targets/` — target directory scan
- `Target '...' loaded with N encoding(s)` — per-target encoding count
- `Loaded N target(s) with N total encoding(s)` — target summary
- `Starting Argus: N camera(s), N target(s), N webhook(s)` — final summary before entering the main loop

If no targets are found: `No targets loaded — Argus will detect faces but cannot identify anyone`

## Exit Behavior

**Graceful shutdown:**

- `Ctrl+C` (SIGINT) — Argus stops all stream threads and exits cleanly
- `'q'` key in GUI mode — closes all display windows and exits

**Error exits (code 1):**

| Condition | Error Message |
|---|---|
| Config directory not found | `Configuration error: Camera config not found: config/cameras.toml` |
| No cameras defined | `Configuration error: No cameras defined in cameras.toml` |
| Camera missing `url` | `Configuration error: Camera 'cam_01' is missing required 'url' field` |
| Invalid settings values | `Configuration error: frame_scale must be in (0, 1], got 0.0` |

## Targets Directory Behavior

| Condition | Behavior |
|---|---|
| Targets directory not found | Warning logged, zero targets loaded, Argus continues (detect-only mode) |
| Target directory missing `info.json` | Warning logged, that target skipped |
| Target `info.json` has no images | Warning logged, that target skipped |
| Target image file not found | Warning logged, that image skipped, other images still processed |
| No face detected in an image | Warning logged, encoding skipped, other images still processed |
| Multiple faces in an image | Warning logged, **first face is used**, other faces ignored |
| All images for a target fail | Error logged, that target skipped entirely |
