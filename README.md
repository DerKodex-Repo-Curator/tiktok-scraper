# TikTok downloader (Docker)

Containerized TikTok profile downloader built on pinned gallery-dl and yt-dlp
forks. It supports incremental downloads, batch files, SOCKS5H/Tor retries,
persistent manifests, and safe archive management. The retained Node.js source
is legacy and is not used by this image.

## Quick start from WSL

Build with the GitHub token required by the private gallery-dl fork:

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
```

Download one public profile and persist all state:

```sh
mkdir -p downloads
docker run --rm \
  -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper USERNAME --range 1
```

Expected terminal output includes per-media status plus `[SUMMARY]` and
`[BACKEND]`. The mounted directory receives media, the SQLite archive, retry
queue when needed, and JSON/CSV manifests.

## Common commands

```sh
# Full profile or direct TikTok URL
docker run --rm -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper USERNAME

# Stop after downloading 5 new videos; archive skips do not consume the quota
docker run --rm -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper USERNAME --new-items 5

# Keep request pacing and add a random 8-12 second pause between media
docker run --rm \
  -e SLEEP_REQUEST=2-5 -e MEDIA_DELAY=8-12 \
  -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper USERNAME

# Sequential batch; mount the input read-only
docker run --rm \
  -v "$(pwd)/downloads:/downloads" \
  -v "$(pwd)/targets.txt:/input/targets.txt:ro" \
  tiktok-scraper from-file /input/targets.txt --range 1

# Inspect or change gallery-dl's archive
docker run --rm -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper history list
docker run --rm -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper history remove VIDEO_ID
docker run --rm -v "$(pwd)/downloads:/downloads" \
  tiktok-scraper history clear --yes
```

Targets files accept one username, `@username`, or HTTP(S) TikTok URL per line.
Blank lines and lines beginning with `#` are ignored. Arguments after a target
or batch file are forwarded to gallery-dl.

`SLEEP_REQUEST` remains gallery-dl's per-request pacing (default `2-5`).
`MEDIA_DELAY` is optional and accepts a fixed number or range such as `8-12`.
It pauses once before the next media after a downloaded, skipped, or failed
media item; it does not add a final pause after the last known item.

`--new-items N` is a wrapper option, not a gallery-dl option. `N` must be a
positive integer. It stops each single or batch target after `N` newly
downloaded non-avatar media; archived `SKIPPED` items do not consume the quota.
Exhausting the profile first is still successful and reports the real download
count. Do not combine it with gallery-dl's native `--range`; the wrapper rejects
that ambiguous combination instead of guessing which limit should win.

The pinned gallery-dl fork streams TikTok profile pages into archive checks and
media processing. Consequently `--new-items` can stop pagination as soon as its
new-download quota is satisfied; it does not need to enumerate the full profile.

## Documentation

| Need | Read |
|---|---|
| Understand components and data flow | [Architecture](docs/ARCHITECTURE.md) |
| Run, configure, smoke-test, or publish manually | [Operations](docs/OPERATIONS.md) |
| Diagnose build, network, TikTok, or persistence failures | [Troubleshooting](docs/TROUBLESHOOTING.md) |
| See completed and planned work | [Roadmap](ROADMAP.md) |

## Legacy source

`bin/`, `src/`, and `examples/CLI/` belong to the archived Node.js scraper.
Commands such as legacy `hashtag`, `trend`, `music`, and JSON history management
are not implemented by this Docker wrapper. Legacy examples are retained only
as project history and are marked accordingly.
