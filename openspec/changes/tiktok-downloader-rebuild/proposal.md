# Proposal: TikTok Downloader Rebuild

## Intent
Rebuild the obsolete Node.js TikTok scraper as a stable Python-based downloader
using yt-dlp as the download engine, delivered in 4 layers: CLI binary, Docker
image, REST API, and Web UI.

## Motivation
The original drawrowfly/tiktok-scraper Node.js code is obsolete. TikTok changed
its API and the signing mechanism no longer works. A previous attempt using
gallery-dl + yt-dlp (branch feature/docker-downloader) hit upstream bugs in
gallery-dl (AttributeError on False entries, urllib3 403s). This rebuild uses
yt-dlp directly with custom Python orchestration, avoiding gallery-dl entirely.

## Scope

### In Scope
- Stable Python CLI binary using yt-dlp (single + batch profile downloads)
- Docker container for containerized execution
- REST API with OpenAPI/Swagger documentation (Scalar)
- Web UI with modern UX for profile browsing/downloads

### Out of Scope (for now)
- Hashtag/music feed scraping
- OAuth authentication
- Video transcription (Whisper)
- Trending feed integration

## Capabilities

### New Capabilities
- `tiktok-downloader-cli`: Command-line tool for profile downloads
- `tiktok-docker`: Containerized version for isolated execution
- `tiktok-api`: REST API for programmatic access
- `tiktok-ui`: Web interface with responsive design

## Approach

### Architecture: Hybrid (yt-dlp direct, no gallery-dl)
1. **Download engine**: yt-dlp with curl-cffi (--impersonate chrome)
2. **Profile enumeration**: yt-dlp --flat-playlist --dump-json
3. **Video download**: yt-dlp -f best (configurable via VIDEO_FORMAT)
4. **Custom Python orchestration**: metadata, manifests, retry, proxy rotation
5. **Storage**: JSON + CSV + SQLite manifests for portability

### Key technical decisions (verified in testing)
- Proxy: SOCKS5 with Tor identity rotation (isolated_proxy)
- Cookies: Netscape format, mountable as volume
- Skip detection: yt-dlp --download-archive + custom SQLite manifest
- Watchdog: kill hung processes after PROFILE_TIMEOUT (default 120s)
- Retry: up to PROFILE_MAX_ATTEMPTS (default 3) with Tor identity rotation
- Rate limiting: SLEEP_REQUEST (2-5s), MEDIA_DELAY (optional)

### SDD/TDD/BDD approach
- TDD: tests first for each module (downloader, metadata, manifest, proxy, retry)
- BDD: scenarios for user-facing features (download, batch, skip existing)
- SDD: spec -> design -> tasks -> apply -> verify

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/tiktok_dl/` | New | Core Python package |
| `src/tiktok_dl/downloader.py` | New | yt-dlp integration layer |
| `src/tiktok_dl/manifest.py` | New | JSON/CSV/SQLite manifest storage |
| `src/tiktok_dl/proxy.py` | New | SOCKS5 proxy + Tor rotation |
| `src/tiktok_dl/retry.py` | New | Retry logic with watchdog |
| `src/tiktok_dl/cli.py` | New | CLI entry point |
| `Dockerfile` | New | Containerized execution |
| `api/` | New | FastAPI REST endpoints |
| `ui/` | New | Web interface |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| yt-dlp API changes | Medium | Pin yt-dlp version in Dockerfile |
| Proxy IP blacklisting | High | Tor identity rotation + watchdog timeout |
| Cookie expiration | Medium | Document cookie refresh process |
| TikTok WAF changes | Medium | yt-dlp is actively maintained, update regularly |

## Success Criteria
- [ ] Single profile download working with proxy + cookies
- [ ] Batch download from targets.txt file
- [ ] Skip already-downloaded videos (archive detection)
- [ ] Docker build passing with minimal resources
- [ ] API endpoints documented and testable
- [ ] Web UI functional with basic profile search/download
- [ ] All tests passing (TDD coverage)

## Rollback Plan
1. Previous work preserved in feature/docker-downloader branch
2. Master branch is clean (upstream original)
3. All changes in new branch (feature/tiktok-downloader-rebuild)