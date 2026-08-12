# Proposal: rebuild-downloader-rotation

## Intent

Long-profile TikTok downloads fail because the current flow wraps the entire profile in a single 120s watchdog, persists history only at the end, and rotates IPs via fragile Tor NEWNYM control-port signals. This proposal replaces that with a robust per-item pipeline that rotates IPs by generating fresh proxyto dummy usernames (GUID), persists each download immediately, skips already-downloaded items, and enforces a sane retry policy.

## Scope

### In Scope
- Replace Tor NEWNYM rotation with proxyto GUID-username rotation
- Per-item download pipeline: collect → check-skip → download → persist
- Durable history with `downloaded` / `skipped` / `failed` status per item
- Skip already-downloaded items via manifest + yt-dlp `--download-archive`
- Jittered exponential backoff retry with max 5 attempts
- Downloads folder cleanup policy (test mode vs final mode)
- Separate profile enumeration from per-video download

### Out of Scope
- Web UI changes (existing UI continues to work against the same API)
- Third-party backends (SnapTik etc.) — explicitly excluded
- Cookie refresh / QR login (already handled separately)
- New API endpoints (existing `/api/v1/download` contract preserved)

## Capabilities

### New Capabilities
- `proxy-rotation`: proxyto dummy-user GUID rotation and proxy URL builder
- `download-pipeline`: per-item collect→skip→download→persist pipeline
- `downloads-cleanup`: test-mode and final-mode cleanup of downloads folder

### Modified Capabilities
- `retry-policy`: jittered exponential backoff with per-item retry (not per-profile)
- `manifest-history`: per-item status tracking with downloaded/skipped/failed states
- `profile-enumeration`: separated from download, resumable, paginated

## Approach

1. **Proxy rotation**: `build_proxy_url(uuid4())` returns `socks5h://<guid>:dummy@proxyto.hs.sof.ar:9050`. Each retry gets a fresh GUID → fresh exit IP. No Tor control port.
2. **Pipeline**: `download_profile()` enumerates items (list of video URLs/IDs). For each item: check manifest → if exists, mark `skipped`; else download via `download_video()` with fresh proxy URL → on success persist to manifest immediately; on failure retry up to 5 attempts with jittered backoff and new proxy URL per attempt → mark `failed` if exhausted.
3. **History**: SQLite manifest gains explicit `status` column values: `downloaded`, `skipped`, `failed`. History API and UI read from this.
4. **Cleanup**: `clean_downloads(mode=test)` removes all content from `downloads/` before test runs. `clean_downloads(mode=final)` removes `.part` and `.image` leftovers after a completed run.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/tiktok_dl/proxy.py` | Modified | Replace `rotate_tor_identity()` with `build_proxy_url()` GUID rotation |
| `src/tiktok_dl/retry.py` | Modified | Jittered exponential backoff, per-item retry, remove watchdog-on-profile |
| `src/tiktok_dl/cli.py` | Modified | Pipeline flow: enumerate → per-item skip/download/persist |
| `src/tiktok_dl/downloader.py` | Modified | Accept dynamic proxy URL per call |
| `src/tiktok_dl/manifest.py` | Modified | Per-item status (downloaded/skipped/failed), mid-cycle writes |
| `api/worker.py` | Modified | Pass per-item progress to job store |
| `tests/` | New | TDD/BDD tests for rotation, pipeline, skip, cleanup, history |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| proxyto endpoint unavailable | Low | Verified working; fallback to direct if needed |
| GUID username collision | Negligible | uuid4 |
| Long enumeration still times out | Medium | Paginated enumeration with resumable cursor |
| Manifest write contention | Low | SQLite WAL mode, single-writer |
| Existing tests break | Medium | Update tests alongside code changes |

## Rollback Plan

1. Revert `proxy.py` to `rotate_tor_identity()` NEWNYM approach
2. Revert `cli.py` to end-of-loop manifest writes
3. Revert `retry.py` to watchdog-based retry
4. Revert `manifest.py` to implicit status
5. Revert tests

## Dependencies

- proxyto endpoint (`socks5h://proxyto.hs.sof.ar:9050`) — verified operational
- yt-dlp with `--impersonate chrome` (curl_cffi) — already installed
- No third-party download services

## Success Criteria

- [ ] All connections go through proxyto with GUID dummy usernames
- [ ] Each retry attempt uses a different exit IP (verified via ipify)
- [ ] Long-profile download (100+ videos) completes without watchdog failure
- [ ] Already-downloaded items are skipped, not re-downloaded
- [ ] History shows `downloaded` / `skipped` / `failed` per item
- [ ] `downloads/` cleanup works in test mode and final mode
- [ ] Max retry count enforced (5 attempts, jittered backoff)
- [ ] All existing tests pass or are explicitly updated