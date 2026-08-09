#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
    cat >&2 <<'EOF'
Usage: tiktok-dl USERNAME [--new-items N] [gallery-dl options]
       tiktok-dl URL [gallery-dl options]
       tiktok-dl from-file FILE [--new-items N] [gallery-dl options]
       tiktok-dl --from-file FILE [gallery-dl options]
       tiktok-dl history list [--json]
       tiktok-dl history remove VIDEO_ID
       tiktok-dl history clear --yes

Mount /downloads to persist downloads, the archive, and the retry queue.
JSON and CSV download manifests are maintained in /downloads automatically.
--new-items counts only newly downloaded non-avatar media per target; archive
skips do not count. It cannot be combined with gallery-dl --range.
Optional settings: SLEEP_REQUEST (2-5 request pacing), MEDIA_DELAY (fixed or
random inter-media seconds, for example 8-12), PROFILE_MAX_ATTEMPTS (3),
PROFILE_BASE_DELAY (5 seconds), PROFILE_FAILURE_BUDGET (3 retryable signals),
RETRY_MAX_ATTEMPTS (4), and
RETRY_BASE_DELAY (5 seconds). SOCKS proxies rotate Tor identities on retry by
default; configure TOR_ROTATE_ON_RETRY and RETRY_JITTER as needed.
EOF
    exit 2
fi

exec python3 /usr/local/lib/tiktok-dl/retry_runner.py "$@"
