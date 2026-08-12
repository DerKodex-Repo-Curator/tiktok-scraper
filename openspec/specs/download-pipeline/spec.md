# `download-pipeline` Spec

## Purpose

Per-item pipeline: collect URL → check manifest → skip/download → persist status in single atomic step.

## Requirements

### Requirement: Skip Already Downloaded Items

The pipeline SHALL query manifest by video ID before downloading.

#### Scenario: Already downloaded item skipped

- GIVEN a manifest containing video ID `v123` with status `downloaded`
- WHEN pipeline receives `v123` for download
- THEN skips download and marks `skipped`

#### Scenario: New item proceeds to download

- GIVEN manifest has no entry for `v123`
- WHEN `download_pipeline_item(v123)` executes
- THEN passes to `download_video()` with proxy URL

### Requirement: Per-Item Retry Isolation

Each video MUST be retried independently up to 5 times using jittered backoff.

#### Scenario: Item fails all retries

- GIVEN `v123` fails network error 5 times
- WHEN all retries exhausted
- THEN marks `failed` with error message in manifest

#### Scenario: Mid-pipeline crash does not affect other items

- GIVEN items `v123` and `v456` in queue
- WHEN `v123` crashes
- THEN `v456` retries normally without waiting for `v123`

### Requirement: Immediate Manifest Persistence

On successful download, manifest MUST be written synchronously before next item.

#### Scenario: Download succeeds and marks complete

- GIVEN `download_video(v123)` returns success
- WHEN manifest update occurs
- THEN next run skips `v123`