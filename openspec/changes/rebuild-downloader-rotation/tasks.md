# Tasks: rebuild-downloader-rotation

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 300-350 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Not needed |
| Delivery strategy | auto-chain |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | proxy.py: build_proxy_url() with GUID rotation | PR-001 | pytest tests/test_proxy.py::test_build_proxy_url | python -c "from src.tiktok_dl.proxy import build_proxy_url; print(build_proxy_url())" | Revert to rotate_tor_identity() |
| 2 | retry.py: jittered backoff (max 5 attempts) | PR-002 | pytest tests/test_retry.py::test_retry_backoff | python -c "from src.tiktok_dl.retry import retry_with_backoff; print(retry_with_backoff.__doc__)" | Remove watchdog logic |
| 3 | manifest.py: status column + WAL | PR-003 | pytest tests/test_manifest.py::test_status_column | python -c "from src.tiktok_dl.manifest import Manifest; m=Manifest(); print(m.status_col)" | Restore implicit status |
| 4 | cleanup.py: clean_downloads(mode=test|final) | PR-004 | pytest tests/test_cleanup.py::test_clean_downloads_test | python -c "from src.tiktok_dl.cleanup import clean_downloads; clean_downloads('/tmp/test', 'test')" | Remove module |

## Phase 1: Foundation (Proxy, Retry, Manifest)

- [x] 1.1 RED: Write failing test for build_proxy_url() format and uniqueness
- [x] 1.2 GREEN: Implement build_proxy_url() in proxy.py, remove rotate_tor_identity()
- [x] 1.3 RED: Write failing test for jittered backoff (max 5 attempts, early success)
- [x] 1.4 GREEN: Implement retry_with_backoff() in retry.py, remove watchdog
- [x] 1.5 RED: Write failing test for manifest status column (downloaded/skipped/failed)
- [x] 1.6 GREEN: Add status column and enable WAL mode in manifest.py

## Phase 2: Core Implementation (Cleanup, CLI Pipeline)

- [x] 2.1 RED: Write failing test for cleanup.py test/final modes
- [x] 2.2 GREEN: Create cleanup.py with clean_downloads() function
- [x] 2.3 RED: Threat-matrix test: proxyto unavailable → item marked failed after 5 attempts
- [x] 2.4 RED: Threat-matrix test: subprocess timeout → item marked failed
- [x] 2.5 GREEN: Rework cli.py pipeline (enumerate → per-item skip/download/persist)
- [x] 2.6 GREEN: Update worker.py for per-item progress reporting

## Phase 3: Testing / Verification

- [x] 3.1 Threat-matrix test: IP rotation not effective → log warning, continue
- [x] 3.2 Threat-matrix test: update existing tests + verify full suite passes
- [x] 3.3 Integration: pipeline skips already-downloaded items (verify manifest)
- [x] 3.4 Integration: pipeline persists each download immediately after success
- [x] 3.5 Integration: pipeline marks failed after 5 exhausted retries

## Phase 4: Cleanup / Documentation

- [x] 4.1 Update README with new rollout order and usage examples
- [x] 4.2 Document rollback procedure for each phase

Rollback boundaries after each PR as shown in work units table.