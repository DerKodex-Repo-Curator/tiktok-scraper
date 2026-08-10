# Operations guide

Use this guide to build, run, verify, and manually publish the image. There is
no CI/CD workflow in this repository.

## Prerequisites

- WSL shell with a working Docker daemon.
- GitHub CLI authenticated with access to the private gallery-dl fork.
- A writable host directory mounted at `/downloads`.

## Build

```sh
cd /mnt/c/Dev/tiktok-scraper
gh auth status
(
  export GH_TOKEN="$(gh auth token)"
  test -n "$GH_TOKEN"
  DOCKER_BUILDKIT=1 docker build --no-cache \
    --secret id=github_token,env=GH_TOKEN \
    -t tiktok-scraper .
)
docker image inspect tiktok-scraper --format '{{.Id}} {{.Created}}'
```

Never pass the token with `--build-arg` or embed it in a repository URL.

## Run with Tor

Build the local Tor image, create one Docker network, and wait for health:

```sh
cd /mnt/c/Dev/torproxy
docker build --no-cache -t torproxy-local .
docker network inspect tiktok-net >/dev/null 2>&1 || \
  docker network create tiktok-net
docker rm -f torproxy 2>/dev/null || true
docker run -d \
  --name torproxy \
  --restart unless-stopped \
  --network tiktok-net \
  -p 127.0.0.1:9050:9050 \
  torproxy-local
docker inspect --format '{{.State.Health.Status}}' torproxy
```

After it reports `healthy`:

```sh
cd /mnt/c/Dev/tiktok-scraper
mkdir -p downloads
docker run --rm \
  --network tiktok-net \
  -v "$(pwd)/downloads:/downloads" \
  -e SOCKS_PROXY_URL='socks5h://torproxy:9050' \
  tiktok-scraper USERNAME --range 1
```

Use `torproxy`, not `127.0.0.1`, inside the downloader container. Docker DNS
resolves the container name on `tiktok-net`; container loopback resolves itself.

## Run with an external SOCKS5H proxy

When the proxy is reachable from WSL and Docker, pass its hostname and port
directly. `socks5h` keeps DNS resolution on the proxy side:

```sh
cd /mnt/c/Dev/tiktok-scraper
mkdir -p downloads
docker run --rm \
  -v "$(pwd)/downloads:/downloads" \
  -e SOCKS_PROXY_URL='socks5h://proxy.example.internal:9050' \
  tiktok-scraper USERNAME --range 1
```

No Docker network is required for an externally reachable proxy. If the proxy
requires authentication, provide credentials through local runtime
configuration and never commit or publish them.

## Cookies

Mount Netscape-format cookies read-only. The default path is
`/cookies/cookies.txt`:

```sh
docker run --rm \
  -v "$(pwd)/downloads:/downloads" \
  -v "$(pwd)/cookies.txt:/cookies/cookies.txt:ro" \
  tiktok-scraper USERNAME --range 1
```

For another in-container path, set `COOKIES_FILE` to that mounted file. Cookie
files contain active credentials; never commit or publish them.

## Verified configuration

| Variable | Behavior |
|---|---|
| `SOCKS_PROXY_URL` | Preferred explicit HTTP/HTTPS/SOCKS proxy URL |
| `ALL_PROXY` | Used only when `SOCKS_PROXY_URL` is unset |
| `TOR_ROTATE_ON_RETRY` | Overrides automatic rotation for SOCKS proxies |
| `RETRY_JITTER` | Non-negative retry jitter fraction; default `0.2` |
| `SLEEP_REQUEST` | gallery-dl request pacing; default `2-5` |
| `MEDIA_DELAY` | Optional fixed seconds or random range between terminal media, for example `8-12`; empty disables it |
| `PROFILE_MAX_ATTEMPTS` | Native profile attempts; default `3` |
| `PROFILE_BASE_DELAY` | Profile retry base delay; default `5` seconds |
| `PROFILE_FAILURE_BUDGET` | Retryable failure signals allowed per profile subprocess; default `3` |
| `RETRY_MAX_ATTEMPTS` | Persistent direct-video attempts; default `4` |
| `RETRY_BASE_DELAY` | Direct retry base delay; default `5` seconds |
| `TIKTOK_FORCE_FALLBACK` | `1`, `true`, or `yes` skips native profile attempts |
| `COOKIES_FILE` | In-container cookie file path |
| `DOWNLOADS_DIR` | Runtime state directory; image default is `/downloads` |
| `GALLERY_DL_BIN` | gallery-dl executable name/path; default `gallery-dl` |

`MEDIA_DELAY` applies exactly once before a subsequent media item after a
downloaded, archive-skipped, or failed non-avatar item. It does not replace
`SLEEP_REQUEST`, retry backoff, or Tor rotation. It does not require FFmpeg.

Use `--new-items N` after a single target or batch file to cap newly downloaded
media per target. `N` is a positive integer. Archive skips do not count, and
content exhaustion below the quota is successful. `--new-items` and gallery-dl
`--range` are intentionally rejected together because they express different
limits.

The pinned gallery-dl fork streams profile pages. `--new-items` can therefore
stop further pagination once N new downloads complete, while archive skips
continue through subsequent items and pages without consuming the quota.

## Smoke tests

Run these manually after changing the wrapper, Dockerfile, or pinned forks.

1. **Local unit and syntax checks**

   ```sh
   python -m unittest -v test_retry_runner.py test_docker_assets.py
   python -m py_compile retry_runner.py
   sh -n docker-entrypoint.sh
   git diff --check
   ```

2. **Single-target download**

   ```sh
   docker run --rm -v "$(pwd)/downloads:/downloads" \
     tiktok-scraper USERNAME --range 1
   ```

   Confirm `[SUMMARY]`, `[BACKEND]`, media output, archive, and both manifests.

3. **Incremental repeat**

   Run the same command again. Confirm a `SKIPPED` event and no duplicate
   manifest row for the same target and video ID.

4. **Sequential batch through Tor**

   Mount a two-target file read-only and run `from-file` with
   `SOCKS_PROXY_URL=socks5h://torproxy:9050`. Confirm per-target summaries and
   `[BATCH SUMMARY]`.

5. **Archive management**

   ```sh
   docker run --rm -v "$(pwd)/downloads:/downloads" \
     tiktok-scraper history list
   ```

   Test `history remove VIDEO_ID` only with a disposable record. Confirm the
   retry queue and manifests remain present.

## Manual publication

Publishing is deliberate and manual. After all smoke tests pass:

```sh
IMAGE='<registry>/<namespace>/tiktok-scraper:<tag>'
docker tag tiktok-scraper "$IMAGE"
docker image inspect "$IMAGE" --format '{{.Id}} {{.RepoTags}}'
docker login '<registry>'
docker push "$IMAGE"
```

Use an immutable, reviewed tag. Record the image digest and the two pinned fork
SHAs in the release notes. Never publish `downloads`, targets, cookies, tokens,
or local environment files.
