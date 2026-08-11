# tiktok-dl

Python TikTok downloader using **yt-dlp** (direct, no gallery-dl) with
SOCKS5 proxy + Tor identity rotation. Delivered in 4 layers: CLI, Docker,
REST API, and Web UI.

## Features

- **yt-dlp direct** with curl-cffi (`--impersonate chrome`) to bypass TikTok WAF
- **SOCKS5 proxy** with Tor identity rotation (NEWNYM) on failure
- **Netscape cookies** for authenticated downloads
- **Manifest storage**: JSON + CSV + SQLite for portability
- **Skip detection**: `--download-archive` synced with SQLite manifest
- **Retry + watchdog**: exponential backoff, 120s timeout, up to 3 attempts
- **REST API** with OpenAPI/Swagger docs
- **Web UI** with HTMX (no SPA framework, responsive)

## Requirements

- Python 3.14+
- yt-dlp, curl-cffi, PySocks, FastAPI, Uvicorn, Pydantic v2

## Quick start (CLI)

```sh
# Install
pip install -e ".[dev]"

# Download a single video
tiktok-dl https://tiktok.com/@user/video/123 --cookies-file cookies.txt

# Download a profile (latest 10 videos)
tiktok-dl @username --range 10 --cookies-file cookies.txt

# Batch download from file
tiktok-dl --from-file targets.txt --cookies-file cookies.txt

# With custom proxy
tiktok-dl @user --proxy socks5h://proxy:9050 --cookies-file cookies.txt
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_URL` | `socks5h://proxyto.hs.sof.ar:9050` | SOCKS5 proxy URL |
| `COOKIE_FILE` | — | Path to Netscape cookies file |
| `VIDEO_FORMAT` | `best` | yt-dlp format selector |
| `PROFILE_TIMEOUT` | `120` | Watchdog timeout in seconds |
| `PROFILE_MAX_ATTEMPTS` | `3` | Retry attempts |
| `SLEEP_REQUEST` | `2-5` | Delay between requests |

## REST API

```sh
# Start the server
uvicorn api.main:app --host 0.0.0.0 --port 8000

# OpenAPI docs
open http://localhost:8000/docs
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/download` | Start a download job |
| `GET` | `/api/v1/jobs` | List all jobs |
| `GET` | `/api/v1/jobs/{id}` | Get job status |
| `GET` | `/api/v1/history` | List downloaded videos (paginated) |
| `DELETE` | `/api/v1/history/{video_id}` | Delete a history record |
| `GET` | `/api/v1/health` | Health check |

## Web UI

```sh
uvicorn api.main:app --host 0.0.0.0 --port 8000
# Open http://localhost:8000
```

- `/` — Download form (enter username/URL)
- `/history` — Browse downloaded videos
- `/settings` — Configure proxy, cookies, video format

## Docker

```sh
# Build
docker build -t tiktok-dl .

# Run API server
docker run -p 8000:8000 \
  -v ./downloads:/downloads \
  -v ./cookies:/cookies \
  -e COOKIE_FILE=/cookies/cookies.txt \
  tiktok-dl

# Run CLI instead of API
docker run -v ./downloads:/downloads -v ./cookies:/cookies tiktok-dl \
  python -m tiktok_dl.cli @username --cookies-file /cookies/cookies.txt
```

### Volume mounts

| Mount | Description |
|-------|-------------|
| `/downloads` | Downloaded videos and manifests |
| `/cookies` | Netscape-format cookies file |
| `/config` | Optional configuration |

## Cookies

Export TikTok session cookies in **Netscape format** from a logged-in browser
session (use a Playwright browser session or a browser extension like
"Get cookies.txt").

## Testing

```sh
# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/test_downloader.py tests/test_cli.py -v
```

## Architecture

```
src/tiktok_dl/
  __init__.py     — public API exports
  downloader.py   — yt-dlp subprocess wrapper
  manifest.py     — JSON/CSV/SQLite manifest store
  proxy.py         — SOCKS5 + Tor NEWNYM rotation
  retry.py        — retry + watchdog + error classification
  cli.py          — argparse CLI entry point

api/
  main.py         — FastAPI app + UI routes
  router.py       — /api/v1/* endpoints
  models.py       — Pydantic v2 models

ui/
  templates/      — Jinja2 templates (base, index, history, settings)
  static/         — CSS + HTMX loader
```

## Why yt-dlp direct (no gallery-dl)?

The previous approach used `gallery-dl` + `yt-dlp` but hit upstream bugs:
- `gallery-dl` uses `urllib3` which gets 403 from TikTok WAF (no TLS fingerprint)
- `gallery-dl` `AttributeError: 'bool' object has no attribute 'get'` when
  `yt-dlp` returns `False` entries
- `gallery-dl` normalizes URLs stripping share-link params

`yt-dlp` with `curl-cffi` (`--impersonate chrome`) + SOCKS5 + cookies works
reliably: enumerates profiles, extracts formats, and downloads videos.