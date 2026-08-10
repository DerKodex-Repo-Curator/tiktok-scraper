# Troubleshooting

Start with the symptom below, verify the listed evidence, then apply the narrow
fix. Do not delete persistent state as a first response.

## Build cannot fetch the private gallery-dl fork

**Check**

```sh
gh auth status
test -n "$(gh auth token)"
```

Build with BuildKit and the required secret exactly as documented in
[Operations](OPERATIONS.md). A normal `docker build` without
`--secret id=github_token,env=GH_TOKEN` cannot fetch the private fork. Do not
move the token into an ARG, ENV, or URL.

## Entrypoint reports `no such file or directory`

If the script exists in the image but Linux still reports this error, verify
that `docker-entrypoint.sh` uses LF rather than CRLF line endings. A CRLF
shebang can make the kernel look for an invalid interpreter path.

```sh
python -m unittest -v test_docker_assets.py
```

Do not work around this by changing the container command. Restore LF line
endings and rebuild the image.

## Downloader cannot reach Tor

`Connection refused` usually means the address or Docker network is wrong. It
does not trigger circuit rotation.

```sh
docker inspect --format '{{.State.Health.Status}}' torproxy
docker network inspect tiktok-net
```

Both containers must join `tiktok-net`. Use
`socks5h://torproxy:9050` from the downloader; `127.0.0.1` points back to the
downloader container.

## TikTok returns challenge, 403, 429, or timeout

The wrapper classifies these as retryable. With a SOCKS proxy and default
settings, the next attempt receives new SOCKS credentials for Tor
`IsolateSOCKSAuth`. It also applies exponential backoff with jitter. Inspect
`[BACKEND]` to see whether native gallery-dl or the yt-dlp enumerator completed
the profile. Repeated rejection can still end in `result=FAILED`.

One profile subprocess stops after `PROFILE_FAILURE_BUDGET` retryable signals
(default `3`), then uses normal backoff, Tor rotation when configured, and
fallback. The pinned fork streams profile pages, so reaching a new-item quota
also stops later pagination requests.

## Profile is private, missing, or unsupported

These are permanent failures. The wrapper does not rotate Tor identity for
them. Verify the target is a username, `@username`, or HTTP(S) TikTok URL and
that the profile is publicly accessible or usable with the mounted cookies.

## Media pacing configuration is rejected

`MEDIA_DELAY` must be empty, a non-negative number such as `8`, or an ascending
range such as `8-12`. Negative, reversed, non-numeric, and non-finite values
stop before download with a configuration error. `SLEEP_REQUEST` has separate
gallery-dl semantics and remains available.

## New-item quota is rejected

`--new-items` requires one positive integer. It cannot be combined with
gallery-dl `--range`; choose the new-download quota or the native positional
range explicitly. In batch mode the quota resets for each target.

If many pagination pages appear before the first `SKIPPED` or `DOWNLOADED`,
verify the image uses the gallery-dl SHA documented in Architecture. Older image
pins accumulated the complete profile before returning media URLs and must be
rebuilt rather than repaired through archive changes.

## Batch file is rejected

The file must exist inside the container. Mount it read-only and pass that
in-container path:

```sh
-v "$(pwd)/targets.txt:/input/targets.txt:ro"
```

Each non-comment line must be a username, `@username`, or TikTok URL. Blank
lines and lines starting with `#` are ignored. Legacy hashtag, music, and user-ID
batch syntax is intentionally unsupported.

## Manifest is reported corrupt

JSON is canonical and CSV must contain the same ordered dataset. If either is
malformed or they disagree, the wrapper stops before downloading and preserves
both files.

1. Stop downloader containers using the mount.
2. Copy both manifest files outside `/downloads` for investigation.
3. Repair both consistently or move both away explicitly.
4. Run a one-item smoke test to create a new pair if both were moved.

Never delete only one file and assume the other will be trusted.

## Archive commands fail

`history` expects `.gallery-dl-archive.sqlite3` with gallery-dl's
`archive(entry TEXT PRIMARY KEY)` schema. Missing or unexpected schemas return
exit code 2. `history remove` returns 1 when no exact video ID matches.
`history clear` requires `--yes` and preserves the SQLite file.

Archive commands never modify `.tiktok-retry-queue.json` or the manifests.

## Files are owned by root in WSL

Run the container with the host user's numeric IDs:

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper USERNAME --range 1
```

The mounted directory must already be writable by that user.

## Collect a safe diagnostic snapshot

Capture status and structure, not secrets:

```sh
docker image inspect tiktok-scraper --format '{{.Id}} {{.Created}}'
docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' torproxy
ls -la downloads
```

Do not paste cookies, proxy URLs with credentials, `GH_TOKEN`, raw manifests
containing target history, or retry-queue contents into public reports.
