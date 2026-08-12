# Design: rebuild-downloader-rotation

## Technical Approach

Replace Tor NEWNYM-based rotation with proxyto GUID-username model and implement a per-item download pipeline. The profile is first enumerated into a list of items; each item is then independently checked, downloaded, and persisted — no global watchdog wraps the entire profile.

## Architecture Decisions

### Decision: Proxy Rotation via GUID-Based Usernames

**Choice**: `build_proxy_url(uuid4())` → `socks5h://<guid>:dummy@proxyto.hs.sof.ar:9050`
**Alternatives considered**: Round-robin proxy list, Tor control-port NEWNYM rotation
**Rationale**: Eliminates fragile Tor control-port dependency. Each GUID generates a fresh exit IP (verified via ipify: 3 distinct IPs from 3 distinct usernames). Simple, stateless, no external control protocol.

### Decision: Per-Item Retry with Jittered Backoff

**Choice**: Max 5 attempts per item, exponential backoff with ±50% jitter. No global watchdog on the whole profile.
**Alternatives considered**: Global watchdog timer (current 120s), fixed-delay retry
**Rationale**: Prevents cascading failures in long profiles. Isolates retries per item so one stuck video doesn't kill the entire profile run. Jitter prevents thundering-herd against proxyto.

### Decision: SQLite WAL with Explicit Status Column

**Choice**: Add `status` column with values `downloaded`, `skipped`, `failed` to the existing SQLite manifest. Enable WAL mode for write concurrency safety.
**Alternatives considered**: File-based flags, in-memory cache, separate status table
**Rationale**: Durable, queryable, compatible with existing manifest infrastructure. WAL mode prevents write contention from concurrent workers. Status enables accurate UI reporting and skip logic.

### Decision: Separate Enumeration from Download

**Choice**: `download_profile()` returns a list of items; a separate loop processes each item independently.
**Alternatives considered**: Single-pass enumerate-and-download (current approach)
**Rationale**: Enumeration can be retried/refreshed independently. Download loop can skip/persist per-item. If the process crashes mid-profile, already-downloaded items are recorded and skipped on resume.

## Data Flow

```
[Profile URL/Username]
        │
        ▼
[download_profile()] ──→ [List of video items]
        │
        ▼
[For each item]
        │
        ├── manifest.video_exists(id)? ──YES──→ mark "skipped" ──→ next item
        │
        NO
        │
        ▼
[build_proxy_url(uuid4())] ──→ [download_video(url, proxy_url)]
        │
        ├── success ──→ persist to manifest ("downloaded") ──→ next item
        │
        ├── failure ──→ retry (max 5, jittered backoff, fresh proxy per attempt)
        │                   └── exhausted ──→ mark "failed" ──→ next item
        │
        ▼
[Post-process: thumbnails, cleanup .part/.image]
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/tiktok_dl/proxy.py` | Modify | Replace `rotate_tor_identity()` with `build_proxy_url(guid)` |
| `src/tiktok_dl/retry.py` | Modify | Replace watchdog with per-item jittered exponential backoff |
| `src/tiktok_dl/cli.py` | Modify | Pipeline: enumerate → per-item skip/download/persist loop |
| `src/tiktok_dl/downloader.py` | Modify | Accept dynamic `proxy_url` per call (already does, ensure consistency) |
| `src/tiktok_dl/manifest.py` | Modify | Add `status` column (downloaded/skipped/failed), enable WAL |
| `src/tiktok_dl/cleanup.py` | Create | `clean_downloads(mode=test|final)` function |
| `api/worker.py` | Modify | Pass per-item progress updates to job store |
| `tests/test_proxy.py` | Modify | Test `build_proxy_url()` instead of `rotate_tor_identity()` |
| `tests/test_cli.py` | Modify | Test pipeline: skip, download, persist, retry, cleanup |
| `tests/test_manifest.py` | Modify | Test status column values |
| `tests/test_cleanup.py` | Create | Test cleanup modes |

## Interfaces / Contracts

```python
# src/tiktok_dl/proxy.py
import uuid

PROXYTO_HOST = "proxyto.hs.sof.ar"
PROXYTO_PORT = 9050
PROXYTO_PASSWORD = "dummy"

def build_proxy_url(guid: str | None = None) -> str:
    """Build a proxyto SOCKS5 URL with a GUID dummy username.
    If guid is None, generates a new uuid4.
    Each call with a new guid yields a different exit IP.
    """
    if guid is None:
        guid = str(uuid.uuid4())
    return f"socks5h://{guid}:{PROXYTO_PASSWORD}@{PROXYTO_HOST}:{PROXYTO_PORT}"

# src/tiktok_dl/retry.py
def retry_with_backoff(
    fn,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: float = 0.5,
) -> tuple[bool, Exception | None]:
    """Retry fn with jittered exponential backoff. Returns (success, last_error)."""

# src/tiktok_dl/manifest.py
# status column added to videos table: TEXT DEFAULT 'downloaded'
# values: 'downloaded' | 'skipped' | 'failed'

# src/tiktok_dl/cleanup.py
def clean_downloads(download_dir: str, mode: str = "final") -> None:
    """mode='test': remove all contents of download_dir.
    mode='final': remove only .part and .image files."""
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `build_proxy_url()` generates valid URLs with unique GUIDs | Assert URL format, uniqueness across calls |
| Unit | `retry_with_backoff()` respects max_attempts and applies jitter | Mock fn that fails N times, assert attempt count and delay range |
| Unit | `clean_downloads()` test mode wipes all, final mode removes only .part/.image | Create temp dir with mixed files, assert results |
| Unit | Manifest status column accepts downloaded/skipped/failed | Insert records, query by status |
| Integration | Pipeline skips already-downloaded items | Mock download_profile returning 2 items, first already in manifest, assert skip |
| Integration | Pipeline persists each download immediately | Mock download_video, assert manifest.add_video called per success |
| Integration | Pipeline marks failed after 5 exhausted retries | Mock download_video always failing, assert status=failed |
| E2E | Long-profile download completes without watchdog failure | Docker run with real profile (manual / CI) |

## Threat Matrix

| Threat | Applicable? | Safe/Failure Behavior | RED Test |
|--------|-------------|----------------------|----------|
| Proxyto endpoint unavailable | Applicable | `download_video` returns non-zero; item marked `failed` after 5 attempts | Mock proxy unreachable, assert failed status |
| GUID username collision | N/A | uuid4 entropy sufficient; not a realistic threat | — |
| IP rotation not effective (same IP) | Applicable | Log warning, continue with same IP; not a hard failure | Mock ipify returning same IP, assert warning logged |
| Manifest write contention | N/A | SQLite WAL mode handles single-writer concurrency | — |
| Subprocess timeout (yt-dlp hangs) | Applicable | Per-item subprocess timeout (120s); item marked `failed` | Mock subprocess timeout, assert failed status |
| Existing tests break | Applicable | Update tests alongside code; run full suite | `pytest tests/` must pass |

## Migration / Rollout

No data migration required — the `status` column is added with `DEFAULT 'downloaded'`, so existing records are treated as downloaded. The `rotate_tor_identity` function is removed; any callers are updated to use `build_proxy_url()`.

Rollout order:
1. `proxy.py` — `build_proxy_url()` + remove `rotate_tor_identity()`
2. `retry.py` — per-item jittered backoff + remove watchdog
3. `manifest.py` — add `status` column + WAL
4. `cleanup.py` — new module
5. `cli.py` — pipeline rework
6. `worker.py` — per-item progress
7. Tests — update and add

## Open Questions

- [ ] Should rate limits be enforced per-GUID or globally across all proxyto connections?
- [ ] Should parallel downloads use different GUIDs concurrently, or stay sequential?
- [ ] What is the ideal subprocess timeout per video (currently 120s — may need tuning for HD)?