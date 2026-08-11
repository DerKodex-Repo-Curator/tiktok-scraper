# Design: TikTok Downloader Rebuild

## Technical Approach

Rebuild the obsolete Node.js TikTok scraper as a stable Python-based downloader using yt-dlp with curl-cffi for TLS fingerprint impersonation. The system is delivered in four layers: CLI binary, Docker image, REST API, and Web UI. Core orchestration lives in the `src/tiktok_dl` Python package, which handles profile enumeration, video download, manifest storage, proxy rotation, retry logic, and watchdog timeouts. The API and UI are thin layers that delegate to the same core package, ensuring consistent behavior across interfaces.

## Architecture Decisions

### Decision: Download Engine – yt-dlp via Subprocess
**Choice**: Invoke yt-dlp as a subprocess using the `yt-dlp` command-line interface.
**Alternatives considered**: 
- Use yt-dlp Python API directly.
- Keep gallery-dl as a fallback.
**Rationale**: 
- Subprocess approach isolates yt-dlp version and dependencies, simplifying upgrades.
- The yt-dlp Python API is less documented and may change; CLI is stable.
- Gallery-dl introduced upstream bugs (urllib3 403, AttributeError) and is omitted per constraints.
- Subprocess enables easy injection of curl-cffi via `--impersonate chrome` and SOCKS5 proxy.

### Decision: Manifest Storage – Hybrid JSON/CSV/SQLite
**Choice**: Maintain three manifest formats simultaneously: JSON (human‑readable), CSV (spreadsheet), and SQLite (programmatic query).
**Alternatives considered**: 
- Single format (JSON only).
- Rely solely on yt-dlp’s `--download-archive` file.
**Rationale**: 
- JSON and CSV provide portability and easy inspection.
- SQLite enables efficient lookups for skip detection and history queries.
- Sync logic ensures `--download-archive` stays in sync with SQLite for yt-dlp’s native skip detection.
- This hybrid approach satisfies the spec’s requirement for JSON, CSV, and SQLite manifests.

### Decision: Proxy & Retry – Tor Identity Rotation via Control Port
**Choice**: Rotate Tor identity by sending a `SIGNAL NEWNYM` to the Tor control port on failure.
**Alternatives considered**: 
- Restart the entire Tor process.
- Change SOCKS5 proxy to a different exit node via external script.
**Rationale**: 
- Control port signal is lightweight, fast, and does not disrupt other circuits.
- Aligns with the verified proxy (`socks5h://proxyto.hs.sof.ar:9050`) that exposes a control port.
- Avoids heavyweight process restarts and provides near‑instant identity rotation.

### Decision: API Framework – FastAPI with Pydantic v2
**Choice**: Use FastAPI for the REST API layer, with Pydantic v2 for request/response models.
**Alternatives considered**: 
- Flask + Marshmallow.
- Django REST Framework.
**Rationale**: 
- FastAPI provides async support, automatic OpenAPI/Swagger (Scalar) generation, and high performance.
- Pydantic v2 offers validation, serialization, and IDE autocomplete.
- Matches the spec’s explicit requirement for FastAPI and Scalar UI.

### Decision: UI Implementation – Server‑Rendered HTMX Minimal JS
**Choice**: Build the web UI using FastAPI’s Jinja2 templates enhanced with HTMX for dynamic updates, avoiding heavy SPA frameworks.
**Alternatives considered**: 
- React/Vue SPA.
- Pure server‑side rendered pages with full reloads.
**Rationale**: 
- HTMX enables progressive enhancement with minimal JavaScript, keeping the UI simple and fast.
- Satisfies the spec’s request for a simple web interface (no React/Vue).
- Reduces bundle size and complexity while still providing a responsive experience.

## Data Flow

```
+----------------+        +----------------+        +-------------------+
|   CLI/API/UI   | --->   | tiktok_dl Core | --->   | yt-dlp Subprocess |
+----------------+        +----------------+        +-------------------+
        ^                         |                         |
        |                         v                         v
        |              +----------------+        +-------------------+
        |              | Manifest Sync  | <----> | SQLite/JSON/CSV     |
        |              +----------------+        +-------------------+
        |                         |                         |
        |                +----------------+        +-------------------+
        |                | Proxy/Retry    | <----> | Tor Control Port  |
        |                +----------------+        +-------------------+
        |                         |
        |                +----------------+
        |                | Watchdog       |
        |                +----------------+
```

1. User initiates a download via CLI, API endpoint, or UI form.
2. Core orchestrator parses input, resolves target (username/URL), and prepares yt-dlp arguments.
3. Core invokes yt-dlp as a subprocess with:
   - `--cookies` pointing to Netscape cookie file.
   - `--proxy` set to SOCKS5 URL.
   - `--impersonate chrome` via curl-cffi.
   - `--download-archive` pointing to a temporary archive file.
   - `--flat-playlist --dump-json` for enumeration (if profile).
   - Output template and format selection.
4. yt-dlp downloads videos, writes to `--download-archive`, and emits progress to stdout/stderr.
5. Core monitors the subprocess with a watchdog timer (PROFILE_TIMEOUT).
6. On failure (non‑zero exit, timeout, or retryable error), core signals Tor for NEWNYM, waits, and retries up to PROFILE_MAX_ATTEMPTS.
7. After successful download, core synchronizes the yt-dlp archive with the SQLite manifest, and writes JSON/CSV snapshots.
8. API/UI receive job status updates via background tasks or polling.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/tiktok_dl/__init__.py` | Create | Package initializer exposing public API. |
| `src/tiktok_dl/downloader.py` | Create | yt-dlp subprocess wrapper, argument building, output parsing. |
| `src/tiktok_dl/manifest.py` | Create | JSON, CSV, SQLite manifest handling; sync with yt-dlp archive. |
| `src/tiktok_dl/proxy.py` | Create | SOCKS5 proxy validation, Tor control port communication for NEWNYM. |
| `src/tiktok_dl/retry.py` | Create | Retry loop with exponential backoff, watchdog timeout, error classification. |
| `src/tiktok_dl/cli.py` | Create | CLI entry point using argparse or typer; maps commands to core functions. |
| `Dockerfile` | Create | Multi‑stage build: builder (python:3.14‑slim) installs yt-dlp[default,curl‑cffi] + PySocks; runtime copies only needed files. |
| `api/main.py` | Create | FastAPI app with routes for download, jobs, health, history; uses Pydantic models. |
| `api/models.py` | Create | Pydantic v2 models for job request/response, history items. |
| `api/router.py` | Create | APIRouter grouping versioned endpoints (/api/v1/*). |
| `ui/templates/base.html` | Create | Base Jinja2 template with HTMX includes. |
| `ui/templates/index.html` | Create | Home page with download input and button. |
| `ui/templates/history.html` | Create | History view with pagination and video thumbnails. |
| `ui/templates/settings.html` | Create | Settings panel for proxy, cookies, video format. |
| `ui/static/css/style.css` | Create | Minimal styling for responsive layout. |
| `ui/static/js/htmx.js` | Create | HTMX library (served from CDN or vendored). |
| `tests/test_downloader.py` | Create | Unit tests for downloader module (mock subprocess). |
| `tests/test_manifest.py` | Create | Unit tests for manifest sync and queries. |
| `tests/test_proxy.py` | Create | Unit tests for Tor signal handling. |
| `tests/test_retry.py` | Create | Unit tests for retry logic and watchdog. |
| `tests/test_cli.py` | Create | BDD‑style scenarios for CLI commands. |
| `tests/test_api.py` | Create | Integration tests for FastAPI endpoints (using TestClient). |
| `tests/test_ui.py` | Create | Smoke tests for UI routes (template rendering). |
| `pytest.ini` | Create | pytest configuration for asyncio and test discovery. |
| `requirements.txt` | Create | Runtime dependencies: yt‑dlp[curl‑cffi], PySocks, FastAPI, Uvicorn, pytest, pytest‑asyncio. |
| `.dockerignore` | Create | Exclude source files, test data, etc. from Docker context. |
| `README.md` | Update | Add usage instructions for CLI, Docker, API, UI. |

## Interfaces / Contracts

### Core Package Public Interface (`src/tiktok_dl/__init__.py`)
```python
from .downloader import download_profile, download_video
from .manifest import ManifestStore
from .proxy import rotate_tor_identity
from .retry import retry_with_backoff

__all__ = [
    "download_profile",
    "download_video",
    "ManifestStore",
    "rotate_tor_identity",
    "retry_with_backoff",
]
```

### Downloader Function Signatures
```python
def download_video(url: str, cookies_path: str, proxy_url: str,
                   output_template: str, format_str: str,
                   download_archive: str) -> Tuple[int, str]:
    """
    Invoke yt-dlp to download a single video.
    Returns (exit_code, stdout+stderr).
    """

def download_profile(username: str, cookies_path: str, proxy_url: str,
                     output_template: str, format_str: str,
                     download_archive: str, max_videos: Optional[int]) -> List[Dict]:
    """
    Enumerate profile via --flat-playlist --dump-json, then download each video.
    Returns list of video metadata dicts.
    ```

### ManifestStore Class
```python
class ManifestStore:
    def __init__(self, json_path: str, csv_path: str, sqlite_path: str):
        ...

    def add_video(self, video_id: str, metadata: Dict) -> None:
        ...

    def video_exists(self, video_id: str) -> bool:
        ...

    def get_all(self) -> List[Dict]:
        ...

    def sync_with_yt_dlp_archive(self, archive_path: str) -> None:
        ...
```

### API Request/Response Models (Pydantic v2)
```python
class DownloadRequest(BaseModel):
    target: str  # username or URL

class JobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    progress: Dict[str, int]  # downloaded, skipped, failed, total

class HistoryItem(BaseModel):
    video_id: str
    target: str
    title: str
    url: str
    status: str
    path: str
    updated_at: datetime
```

### CLI Argument Structure
```text
tiktok-dl [OPTIONS] TARGET
  TARGET                     TikTok username or video URL
  --range N                  Limit to N most recent videos
  --new-items N              Skip already downloaded, take next N new
  --from-file FILE           Process each line in FILE as a target
  --output-template TEMPLATE  Output file path template (default: "{username}/{video_id} {title}.{ext}")
  --format FORMAT            yt-dlp format selector (default: "best")
  --cookies-file PATH        Netscape cookies file
  --proxy URL                SOCKS5 proxy URL (overrides env)
  --timeout SECONDS          Profile timeout (default: 120)
  --max-attempts N           Retry attempts (default: 3)
  --sleep-request SECONDS    Delay between requests (default: 2-5)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | downloader.py – argument building, exit code parsing | Mock `subprocess.run`; verify command line and handling of success/failure outputs. |
| Unit | manifest.py – JSON/CSV/SQLite sync, duplicate detection | Use temporary files; assert records added, queried, and synced correctly. |
| Unit | proxy.py – Tor signal handling | Mock socket connection to control port; verify `SIGNAL NEWNYM` sent on failure. |
| Unit | retry.py – watchdog, backoff, error classification | Simulate subprocess hangs and timeouts; assert process kill and retry logic. |
| Unit | cli.py – command parsing, dispatch | Use `CliRunner` (typer) or `subprocess` calls; check exit codes and output. |
| Integration | API endpoints – job creation, status, history | Use `TestClient`; enqueue jobs, poll status, verify history records. |
| Integration | UI routes – template rendering, HTMX interactions | Use `TestClient`; GET pages, POST forms, check for expected HTML fragments. |
| End‑to‑End | Docker build & smoke test | Build image, run container with mocked yt‑dlp (via shim), verify CLI invocation. |
| BDD Scenarios | CLI specs (single video, profile, batch, skip, cookie auth, proxy rotation) | Write pytest‑style scenarios using temporary directories, mock yt‑dlp output files, and assert manifest updates. |

## Threat Matrix

N/A — no routing, shell subprocess, VCS/PR automation, executable‑file classification, or process‑integration boundary beyond the controlled yt‑dlp subprocess (which is sandboxed by design). The subprocess is limited to invoking yt‑dlp with predefined arguments; no arbitrary command execution is possible.

## Migration / Rollout

No migration required. The rebuild replaces the legacy Node.js scraper; existing downloaded videos and manifests can be reused by pointing the new system to the same `/downloads` directory. The manifest sync logic will import existing yt‑dlp archive files on first run.

## Open Questions

- [ ] Should the CLI output template be configurable via environment variable as well as command line?
- [ ] How frequently should the SQLite manifest be vacuumed to avoid bloat?
- [ ] Should the web UI support bulk delete of history items?
- [ ] What is the optimal default for `SLEEP_REQUEST` to balance speed and rate‑limiting?