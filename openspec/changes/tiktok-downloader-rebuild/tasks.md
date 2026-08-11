# Tasks: TikTok Downloader Rebuild

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 2,800-3,200 lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | 5-pr chain |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| PR 1 | Core package (manifest, proxy, retry, downloader) + tests | PR 1 | `pytest tests/test_manifest.py tests/test_proxy.py tests/test_retry.py tests/test_downloader.py -v` | Mocked tempfile + subprocess | src/tiktok_dl/ |
| PR 2 | CLI + tests | PR 2 | `pytest tests/test_cli.py -v` | CliRunner + temp files | src/tiktok_dl/cli.py |
| PR 3 | API + tests | PR 3 | `pytest tests/test_api.py -v` | FastAPI TestClient | api/ |
| PR 4 | UI + tests | PR 4 | `pytest tests/test_ui.py -v` | FastAPI TestClient | ui/ |
| PR 5 | Docker + integration + README | PR 5 | `docker build -t tiktok-dl . && pytest tests/test_integration.py` | docker run + mocks | Dockerfile, README.md |

## Phase 1: Core Package Foundation

- [ ] 1.1 Create `src/tiktok_dl/__init__.py` with public exports
- [ ] 1.2 Create `src/tiktok_dl/manifest.py` — JSON/CSV/SQLite manifest store class
- [ ] 1.3 Create `src/tiktok_dl/proxy.py` — SOCKS5 proxy validation, Tor control port NEWNYM signal
- [ ] 1.4 Create `src/tiktok_dl/retry.py` — Retry with exponential backoff, watchdog, error classification
- [ ] 1.5 Create `src/tiktok_dl/downloader.py` — yt-dlp subprocess wrapper, argument building, output parsing

## Phase 2: Core Package Tests

- [ ] 2.1 Create `tests/test_manifest.py` — unit tests for ManifestStore, sync logic
- [ ] 2.2 Create `tests/test_proxy.py` — unit tests for Tor signal handling, proxy validation
- [ ] 2.3 Create `tests/test_retry.py` — unit tests for watchdog, backoff, error classification
- [ ] 2.4 Create `tests/test_downloader.py` — unit tests for yt-dlp invocation, argument building

## Phase 3: CLI Integration

- [ ] 3.1 Create `src/tiktok_dl/cli.py` — argparse/typer entry point, command dispatch
- [ ] 3.2 Create `tests/test_cli.py` — BDD scenarios for CLI commands (download, batch, skip)

## Phase 4: REST API

- [ ] 4.1 Create `api/models.py` — Pydantic v2 request/response models
- [ ] 4.2 Create `api/router.py` — versioned endpoints (/api/v1/*)
- [ ] 4.3 Create `api/main.py` — FastAPI app with routes, background tasks
- [ ] 4.4 Create `tests/test_api.py` — integration tests for endpoints (TestClient)

## Phase 5: Web UI

- [ ] 5.1 Create `ui/templates/base.html` — Jinja2 base with HTMX includes
- [ ] 5.2 Create `ui/templates/index.html` — Home page with download input/button
- [ ] 5.3 Create `ui/templates/history.html` — History view with pagination/thumbnails
- [ ] 5.4 Create `ui/templates/settings.html` — Settings panel for proxy, cookies, format
- [ ] 5.5 Create `ui/static/css/style.css` — Minimal responsive styling
- [ ] 5.6 Create `ui/static/js/htmx.js` — HTMX library vendor file
- [ ] 5.7 Create `tests/test_ui.py` — Smoke tests for UI routes, template rendering

## Phase 6: Docker Environment

- [ ] 6.1 Create `Dockerfile` — Multi-stage build (python:3.14-slim), yt-dlp[default,curl-cffi], PySocks
- [ ] 6.2 Create `.dockerignore` — Exclude source, tests, dev files
- [ ] 6.3 Create `tests/test_integration.py` — Docker build smoke test

## Phase 7: Project Setup & Configuration

- [ ] 7.1 Create `pyproject.toml` — Project metadata, entry points, dependencies
- [ ] 7.2 Create `requirements.txt` — Pin: yt-dlp[default,curl-cffi], PySocks, FastAPI, uvicorn, pytest
- [ ] 7.3 Create `pytest.ini` — Asyncio mode, test discovery patterns

## Phase 8: Documentation

- [ ] 8.1 Update `README.md` — Usage for CLI, Docker, API, UI; setup instructions