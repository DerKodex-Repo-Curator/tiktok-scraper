# Runtime architecture

The Docker image is a Python orchestration wrapper around pinned gallery-dl and
yt-dlp forks. The legacy Node.js implementation is outside the runtime path.

## Request flow

```text
docker-entrypoint.sh
        |
        v
retry_runner.py -----> gallery-dl native TikTok extraction
        |                         |
        | profile challenge       +--> media + archive events
        v
gallery-dl yt-dlp enumerator (curl-cffi Chrome impersonation)
        |
        +--> gallery-dl still performs downloads and archive writes
```

Each single target and every sequential batch target enters `execute_target`.
That shared path configures cookies, proxy, pacing, archive, status events,
manifest updates, fallback, and direct-video retries.

## Build provenance

The Dockerfile fetches and verifies these default commits:

| Component | Repository | Commit |
|---|---|---|
| gallery-dl | `DerKodex-Repo-Curator/gallery-dl-official` | `48f9f648a5123432458acf121efa9151fda8eba8` |
| yt-dlp | `DerKodex-Repo-Curator/yt-dlp` | `5d6b8c8cd19785c3086ae3a9ec618c45e25eb3bc` |

The gallery-dl repository is private. BuildKit mounts `github_token` only for
its fetch instruction; the token is not an ARG, ENV, repository URL, or runtime
file. Both checkouts must match their requested SHA before wheel creation.
yt-dlp is built with its `default,curl-cffi` extras; PySocks is also installed.

Pins prevent branch movement from silently changing application source. They do
not pin every transitive Python wheel resolved during the build.

## Persistent state

All runtime state belongs under the mounted `/downloads` directory:

| Path | Owner | Purpose |
|---|---|---|
| `.gallery-dl-archive.sqlite3` | gallery-dl | Incremental download archive |
| `.tiktok-retry-queue.json` | wrapper | Failed video IDs, attempts, and owning target |
| `tiktok-download-manifest.json` | wrapper | Canonical versioned audit dataset |
| `tiktok-download-manifest.csv` | wrapper | Deterministic CSV view of the JSON dataset |
| other files/directories | gallery-dl | Downloaded media |

Manifest records contain only `video_id`, `target`, `direct_url`, `status`,
`path`, and UTC `updated_at`. The key is target plus video ID. Cookies, proxy
credentials, and raw errors are not persisted there. JSON and CSV are replaced
through temporary files; corruption or disagreement stops downloads safely.

Archive, retry queue, and manifests are independent. History commands modify
only the SQLite archive. They never remove queue or manifest records.

## Failure and retry model

Profile extraction defaults to three attempts with exponential delay based on
`PROFILE_BASE_DELAY`, then uses gallery-dl's yt-dlp enumerator fallback. Direct
video failures recorded in the queue default to four persistent attempts based
on `RETRY_BASE_DELAY`. `RETRY_JITTER` controls delay jitter.

`SLEEP_REQUEST` is passed unchanged to gallery-dl for HTTP-request pacing.
Optional `MEDIA_DELAY` is wrapper-level media pacing. A gallery-dl `prepare`
event marks the next media: after a prior non-avatar `DOWNLOADED`, `SKIPPED`, or
`FAILED` terminal event, the wrapper pauses the child process, sleeps for one
random value in the configured range, and resumes it. The first item and the
last item have no extra wait. A new retry subprocess starts with no pending
media delay because retry backoff already governs attempts.

The wrapper-owned `--new-items N` quota is enforced from the same terminal
events. Only non-avatar `DOWNLOADED` events count; `SKIPPED` and `FAILED` do
not. At the quota the current gallery-dl process group is terminated and reaped,
so a fallback enumerator child cannot be orphaned. A quota-satisfied target
remains successful even when older retry-queue entries
remain. Batch mode applies a fresh quota independently to each sequential
target. Native extraction, fallback, proxying, pacing, archive, queue, and
manifest handling otherwise use the same pipeline.

For SOCKS proxies, Tor rotation defaults on. A JavaScript challenge, HTTP
403/429, timeout, temporary failure, or connection reset assigns fresh SOCKS
credentials to the next attempt. With Tor `IsolateSOCKSAuth`, that selects an
isolated circuit. Credentials remain stable inside one attempt and are passed to
both gallery-dl and yt-dlp. Connection refusal, proxy configuration/auth errors,
private or missing profiles, and unsupported URLs do not rotate identity.
