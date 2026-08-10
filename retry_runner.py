#!/usr/bin/env python3
"""Run gallery-dl with paced profile retries and a yt-dlp fallback."""

import json
import csv
import os
import random
import re
import secrets
import signal
import sqlite3
import string
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, urlsplit, urlunsplit

DOWNLOADS = Path(os.environ.get("DOWNLOADS_DIR", "/downloads"))
QUEUE = DOWNLOADS / ".tiktok-retry-queue.json"
ARCHIVE = DOWNLOADS / ".gallery-dl-archive.sqlite3"
MANIFEST_JSON = DOWNLOADS / "tiktok-download-manifest.json"
MANIFEST_CSV = DOWNLOADS / "tiktok-download-manifest.csv"
MANIFEST_COLUMNS = ["video_id", "target", "direct_url", "status", "path", "updated_at"]
FAILURE = re.compile(r"(?:\[tiktok\]\[warning\]\s+)?(\d{10,}): Failed to solve JavaScript challenge")
PROFILE_CHALLENGE = re.compile(
    r"(?:@[^:]+|tiktok): (?:Failed to solve JavaScript challenge|Failed to retrieve rehydration data)"
)
PROFILE_TERMINAL_FAILURE = re.compile(
    r"(?:Failed to retrieve rehydration data \(4/4\)|Could not extract any posts|"
    r"Unable to extract .*rehydration|Unable to extract universal data)",
    re.IGNORECASE,
)
RETRYABLE_FAILURE = re.compile(
    r"Failed to solve JavaScript challenge|\b(?:403|429)\b|timed? out|timeout|"
    r"temporarily unavailable|connection reset",
    re.IGNORECASE,
)
NO_ROTATE_FAILURE = re.compile(
    r"connection (?:refused|failed)|proxy(?: configuration)? error|407 Proxy Authentication",
    re.IGNORECASE,
)
PERMANENT_FAILURE = re.compile(
    r"private (?:account|profile)|profile (?:is private|does not exist|not found)|user not found|"
    r"account (?:does not exist|not found|is private)|unsupported URL",
    re.IGNORECASE,
)
# "embedding disabled" is NOT permanent — it's a gallery-dl urllib3 403 that
# yt-dlp (curl-cffi) can bypass. Treat it as retryable so the fallback runs.
EMBEDDING_DISABLED = re.compile(r"embedding disabled", re.IGNORECASE)
PROXY_SECRET = re.compile(r"((?:socks(?:4|5|5h)|https?)://)[^\s/@:]+(?::[^\s/@]*)?@", re.IGNORECASE)
STATUS_PREFIX = "__TIKTOK_DL_STATUS__"
MEDIA_PREPARE_PREFIX = "__TIKTOK_DL_MEDIA_PREPARE__"
STATUS = re.compile(rf"^{STATUS_PREFIX}\s+(DOWNLOADED|SKIPPED|FAILED)\s+(.+)$")
MEDIA_PREPARE = re.compile(rf"^{MEDIA_PREPARE_PREFIX}\s+(.+)$")
SUSPEND_SIGNAL = getattr(signal, "SIGSTOP", 19)
RESUME_SIGNAL = getattr(signal, "SIGCONT", 18)


def proxy_url(environ=None):
    """Return and validate the explicitly configured proxy."""
    env = os.environ if environ is None else environ
    value = env.get("SOCKS_PROXY_URL") or env.get("ALL_PROXY")
    if not value:
        return None
    parsed = urlparse(value)
    allowed = {"socks5h", "socks5", "socks4", "http", "https"}
    if parsed.scheme.lower() not in allowed or not parsed.hostname:
        raise ValueError(
            "SOCKS_PROXY_URL/ALL_PROXY must be a valid proxy URL "
            "(for example socks5h://host:1080)"
        )
    return value


def redact_secrets(value):
    return PROXY_SECRET.sub(r"\1***:***@", value)


def tor_rotation_enabled(proxy, environ=None):
    if not proxy:
        return False
    env = os.environ if environ is None else environ
    configured = env.get("TOR_ROTATE_ON_RETRY")
    if configured is not None:
        return configured.lower() in ("1", "true", "yes", "on")
    return urlsplit(proxy).scheme.lower().startswith("socks")


def isolated_proxy(proxy, token=None):
    """Replace SOCKS credentials to select a new IsolateSOCKSAuth circuit."""
    parsed = urlsplit(proxy)
    if not parsed.scheme.lower().startswith("socks"):
        return proxy
    identity = token or secrets.token_urlsafe(18)
    host = f"[{parsed.hostname}]" if ":" in (parsed.hostname or "") else parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"tiktok-{quote(identity, safe='')}:{quote(identity, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def replace_proxy(command, proxy):
    command = list(command)
    if "--proxy" in command:
        index = command.index("--proxy")
        if proxy:
            command[index + 1] = proxy
        else:
            del command[index:index + 2]
    elif proxy:
        command[:0] = ["--proxy", proxy]
    return command


def retry_delay(attempt, base, environ=None, rng=random.uniform):
    env = os.environ if environ is None else environ
    jitter = max(0.0, float(env.get("RETRY_JITTER", "0.2")))
    raw = base * (2 ** attempt)
    return max(0.0, rng(raw * max(0.0, 1 - jitter), raw * (1 + jitter)))


def parse_media_delay(value):
    """Parse a disabled, fixed, or inclusive random media-delay range."""
    value = value.strip()
    if not value:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?", value)
    if not match:
        raise ValueError("MEDIA_DELAY must be a non-negative number or range (for example 2-5)")
    lower = float(match.group(1))
    upper = float(match.group(2) or match.group(1))
    if not all(map(lambda number: number < float("inf"), (lower, upper))) or lower > upper:
        raise ValueError("MEDIA_DELAY must be a non-negative ascending range")
    return lower, upper


def parse_new_items(args):
    """Remove the wrapper-owned quota option and validate its semantics."""
    cleaned = []
    value = None
    index = 0
    while index < len(args):
        option = args[index]
        if option == "--new-items":
            if value is not None or index + 1 >= len(args):
                raise ValueError("--new-items requires exactly one positive integer")
            value = args[index + 1]
            index += 2
            continue
        if option.startswith("--new-items="):
            if value is not None:
                raise ValueError("--new-items may be specified only once")
            value = option.split("=", 1)[1]
            index += 1
            continue
        cleaned.append(option)
        index += 1
    if value is None:
        return cleaned, None
    if not re.fullmatch(r"[1-9]\d*", value):
        raise ValueError("--new-items requires a positive integer")
    if any(option == "--range" or option.startswith("--range=") for option in cleaned):
        raise ValueError("--new-items cannot be combined with gallery-dl --range")
    return cleaned, int(value)


def classify_failure(line, current=None):
    if EMBEDDING_DISABLED.search(line):
        # gallery-dl says "embedding disabled" when its urllib3 request gets
        # 403; yt-dlp (curl-cffi) can bypass this. Do not classify as permanent.
        return "retryable" if current not in ("permanent", "no_rotate") else current
    if PERMANENT_FAILURE.search(line):
        return "permanent"
    if NO_ROTATE_FAILURE.search(line):
        return "permanent" if current == "permanent" else "no_rotate"
    if RETRYABLE_FAILURE.search(line) and current not in ("permanent", "no_rotate"):
        return "retryable"
    return current


def status_options():
    """Ask gallery-dl for machine-readable, terminal per-file events."""
    return [
        "--Print", f"prepare:{MEDIA_PREPARE_PREFIX} {{subcategory!j}}",
        "--Print", f"after:{STATUS_PREFIX} DOWNLOADED {{id!j}} {{_path!j}} {{subcategory!j}}",
        "--Print", f"skip:{STATUS_PREFIX} SKIPPED {{id!j}} {{_path!j}} {{subcategory!j}}",
        "--Print", f"error:{STATUS_PREFIX} FAILED {{id!j}} {{_path!j}} {{subcategory!j}}",
    ]


class ManifestStore:
    def __init__(self, json_path=MANIFEST_JSON, csv_path=MANIFEST_CSV):
        self.json_path = Path(json_path)
        self.csv_path = Path(csv_path)

    def _load(self):
        if not self.json_path.exists():
            if self.csv_path.exists():
                raise ValueError("corrupt manifest: CSV exists without its canonical JSON file")
            return []
        try:
            payload = json.loads(self.json_path.read_text(encoding="utf-8"))
            records = payload["records"]
            if payload.get("version") != 1 or not isinstance(records, list):
                raise ValueError
            normalized = []
            for record in records:
                if list(record) != MANIFEST_COLUMNS or not all(isinstance(record[column], str) for column in MANIFEST_COLUMNS):
                    raise ValueError
                normalized.append(record)
            normalized.sort(key=lambda record: (record["target"], record["video_id"]))
            if self.csv_path.exists():
                with self.csv_path.open(encoding="utf-8", newline="") as stream:
                    reader = csv.DictReader(stream)
                    csv_records = list(reader)
                if reader.fieldnames != MANIFEST_COLUMNS or csv_records != normalized:
                    raise ValueError
            return normalized
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "corrupt manifest: JSON/CSV was left unchanged; repair or move both manifest files explicitly"
            ) from error

    def records(self):
        return self._load()

    def update(self, target, video_id, status, path):
        records = self._load()
        direct = direct_video_url(target, video_id)
        record = {
            "video_id": str(video_id),
            "target": target,
            "direct_url": direct,
            "status": status,
            "path": path or "",
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        by_key = {(item["target"], item["video_id"]): item for item in records}
        by_key[(record["target"], record["video_id"])] = record
        records = sorted(by_key.values(), key=lambda item: (item["target"], item["video_id"]))
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        json_tmp = self.json_path.with_suffix(self.json_path.suffix + ".tmp")
        csv_tmp = self.csv_path.with_suffix(self.csv_path.suffix + ".tmp")
        json_tmp.write_text(
            json.dumps({"version": 1, "records": records}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with csv_tmp.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
        csv_tmp.replace(self.csv_path)
        json_tmp.replace(self.json_path)


def direct_video_url(target, video_id):
    username = profile_name(target)
    return f"https://www.tiktok.com/@{username}/video/{video_id}" if username else ""


def record_status(manifest, target, status, video_id, path):
    if manifest is not None and target and re.fullmatch(r"\d{10,}", str(video_id)):
        manifest.update(target, str(video_id), status, path or "")


def parse_status_payload(payload):
    decoder = json.JSONDecoder()
    values = []
    remaining = payload.lstrip()
    for _ in range(3):
        value, end = decoder.raw_decode(remaining)
        values.append(value)
        remaining = remaining[end:].lstrip()
    if remaining:
        raise ValueError("unexpected status payload")
    return str(values[0]), str(values[1] or ""), str(values[2] or "")


def show_status(kind, item):
    suffix = " (already downloaded)" if kind == "SKIPPED" else ""
    print(f"[{kind}] {item}{suffix}", flush=True)


def terminate_process_tree(process):
    """Terminate and reap the downloader group without orphaning fallback children."""
    if os.name == "posix":
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def save(queue):
    tmp = QUEUE.with_suffix(QUEUE.suffix + ".tmp")
    tmp.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, QUEUE)


def load():
    try:
        data = json.loads(QUEUE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as error:
        print(f"tiktok-dl: ignoring invalid retry queue: {error}", file=sys.stderr)
        return {}


def run(
    command, queue, queue_target=None, manifest=None, media_delay=None,
    sleep=time.sleep, rng=random.uniform, new_items=None, failure_budget=None,
):
    failed = set()
    completed = set()
    counts = {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 0}
    profile_challenge = False
    profile_terminal_failure = False
    failure_kind = None
    terminal_media_seen = False
    quota_reached = False
    budget_reached = False
    retryable_events = 0
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1, start_new_session=True,
    )
    assert process.stdout is not None
    import threading
    heartbeat_stop = threading.Event()

    # Kill the gallery-dl subprocess if it produces no output for a while.
    # TikTok can leave the connection hanging open without responding, which
    # blocks the read loop forever. A watchdog kills the process so the
    # retry logic can rotate to a fresh Tor identity.
    profile_timeout = float(os.environ.get("PROFILE_TIMEOUT", "45"))
    last_output = [time.time()]
    timed_out = [False]

    def watchdog():
        while not heartbeat_stop.wait(5):
            if time.time() - last_output[0] > profile_timeout:
                print(
                    f"tiktok-dl: no output for {profile_timeout:g}s; killing process",
                    file=sys.stderr, flush=True,
                )
                timed_out[0] = True
                terminate_process_tree(process)
                return
    watchdog_thread = threading.Thread(target=watchdog, daemon=True)
    watchdog_thread.start()

    def heartbeat():
        elapsed = 0
        while not heartbeat_stop.wait(15):
            elapsed += 15
            print(f"tiktok-dl: still running... ({elapsed}s)", file=sys.stderr, flush=True)
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    for line in process.stdout:
        last_output[0] = time.time()
        prepare = MEDIA_PREPARE.match(line.rstrip("\r\n"))
        if prepare:
            try:
                subcategory = json.loads(prepare.group(1))
            except json.JSONDecodeError:
                print(redact_secrets(line), end="", flush=True)
                continue
            if subcategory == "avatar":
                continue
            if terminal_media_seen and media_delay is not None:
                delay = rng(*media_delay)
                if delay > 0:
                    process.send_signal(SUSPEND_SIGNAL)
                    try:
                        print(f"tiktok-dl: next media in {delay:g}s", file=sys.stderr)
                        sleep(delay)
                    finally:
                        process.send_signal(RESUME_SIGNAL)
            terminal_media_seen = False
            continue
        status = STATUS.match(line.rstrip("\r\n"))
        if status:
            kind, payload = status.groups()
            try:
                item, media_path, subcategory = parse_status_payload(payload)
            except (ValueError, json.JSONDecodeError):
                print(redact_secrets(line), end="", flush=True)
                continue
            if subcategory == "avatar":
                continue
            counts[kind] += 1
            if kind in ("DOWNLOADED", "SKIPPED"):
                completed.add(item)
            show_status(kind, item)
            record_status(manifest, queue_target, kind, item, media_path)
            terminal_media_seen = True
            if kind == "DOWNLOADED" and new_items is not None and counts["DOWNLOADED"] >= new_items:
                quota_reached = True
                terminate_process_tree(process)
                break
            continue
        print(redact_secrets(line), end="", flush=True)
        failure_kind = classify_failure(line, failure_kind)
        retryable_line = RETRYABLE_FAILURE.search(line) is not None
        if PROFILE_CHALLENGE.search(line):
            profile_challenge = True
        if PROFILE_TERMINAL_FAILURE.search(line):
            profile_terminal_failure = True
        match = FAILURE.search(line)
        if match:
            video_id = match.group(1)
            failed.add(video_id)
            counts["FAILED"] += 1
            show_status("FAILED", f"{video_id} (JavaScript challenge)")
            queue.setdefault(video_id, {"attempts": 0})
            if queue_target:
                queue[video_id]["target"] = queue_target
            save(queue)  # Survives an interruption immediately after discovery.
            record_status(manifest, queue_target, "FAILED", video_id, "")
        if retryable_line and failure_budget is not None:
            retryable_events += 1
            if retryable_events >= failure_budget:
                print(
                    f"tiktok-dl: retryable failure budget reached ({failure_budget}); "
                    "stopping this profile attempt",
                    file=sys.stderr,
                )
                budget_reached = True
                terminate_process_tree(process)
                break
    # A challenge warning can be followed by a successful fallback or an
    # archive hit. A terminal after/skip event wins and must not stay queued.
    for item in completed:
        if item in queue:
            queue.pop(item, None)
            save(queue)
    failed.difference_update(completed)
    heartbeat_stop.set()
    if quota_reached:
        rc = 0
    elif budget_reached:
        rc = 1
    else:
        rc = process.wait()
    # A profile-level challenge happens before post IDs exist. If gallery-dl
    # emitted no terminal item event, treat even rc=0 as an incomplete scan.
    profile_failed = False if quota_reached else (
        budget_reached or timed_out[0] or profile_terminal_failure
        or (profile_challenge and not completed)
    )
    if timed_out[0] and failure_kind is None:
        failure_kind = "retryable"
    return rc, failed, counts, profile_failed, failure_kind


def add_counts(totals, counts):
    for kind, count in counts.items():
        totals[kind] += count


def run_profile(
    binary, common, extra, url, queue, proxy=None, manifest=None,
    media_delay=None, new_items=None,
):
    """Try native gallery-dl extraction, then its official yt-dlp enumerator."""
    totals = {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 0}
    attempts = max(1, int(os.environ.get("PROFILE_MAX_ATTEMPTS", "3")))
    base_delay = max(0.0, float(os.environ.get("PROFILE_BASE_DELAY", "5")))
    failure_budget = max(1, int(os.environ.get("PROFILE_FAILURE_BUDGET", "3")))
    force_fallback = os.environ.get("TIKTOK_FORCE_FALLBACK", "").lower() in ("1", "true", "yes")

    last_rc, profile_failed, failure_kind = 1, True, None
    attempt_proxy = proxy
    rotate = tor_rotation_enabled(proxy)
    # If Tor rotation is enabled, start with an isolated identity so each
    # profile scan gets a fresh circuit (avoids IP-marked blacklist issues).
    if rotate:
        attempt_proxy = isolated_proxy(proxy)

    def remaining_quota():
        return None if new_items is None else max(0, new_items - totals["DOWNLOADED"])
    if not force_fallback:
        for attempt in range(attempts):
            attempt_common = replace_proxy(common, attempt_proxy)
            last_rc, _, counts, profile_failed, failure_kind = run(
                [binary, *attempt_common, *extra, url], queue, url, manifest,
                media_delay=media_delay, new_items=remaining_quota(),
                failure_budget=failure_budget,
            )
            add_counts(totals, counts)
            if not profile_failed:
                return last_rc, totals, "gallery-dl"
            if failure_kind == "permanent":
                if not any(totals.values()):
                    totals["FAILED"] = 1
                return (last_rc or 1), totals, "gallery-dl"
            if attempt + 1 < attempts:
                if rotate and failure_kind == "retryable":
                    attempt_proxy = isolated_proxy(proxy)
                delay = retry_delay(attempt, base_delay)
                print(
                    f"tiktok-dl: profile challenge; retry {attempt + 2}/{attempts} in {delay:g}s",
                    file=sys.stderr,
                )
                time.sleep(delay)

    print("tiktok-dl: using yt-dlp fallback for profile enumeration", file=sys.stderr)
    if rotate and failure_kind == "retryable":
        attempt_proxy = isolated_proxy(proxy)
    fallback_common = replace_proxy(common, attempt_proxy)
    # Improved impersonation with correct header syntax for yt-dlp
    video_format = os.environ.get("VIDEO_FORMAT", "best")
    socket_timeout = int(os.environ.get("PROFILE_TIMEOUT", "45")) // 2
    ytdlp_args = (
        f"--impersonate chrome:windows-10 -f {video_format} "
        f"--socket-timeout {socket_timeout} "
        "--add-headers \"Referer: https://www.tiktok.com/\" "
        "--add-headers \"Accept-Language: en-US,en;q=0.9\""
    )
    if attempt_proxy:
        ytdlp_args += f" --proxy {attempt_proxy}"
    fallback = [
        "--option", "extractor.tiktok.posts.ytdl=true",
        "--option", "extractor.tiktok.posts.module=yt_dlp",
        # Passed to yt-dlp by gallery-dl. curl-cffi supplies the browser TLS
        # fingerprint used by this impersonation target.
        "--option", f"extractor.tiktok.posts.cmdline-args={ytdlp_args}",
    ]
    # Retry the yt-dlp fallback with fresh Tor identities if the previous
    # attempt hung or failed. TikTok blacklists proxy IPs, so a new circuit
    # often succeeds where the previous one stalled.
    for fallback_attempt in range(attempts):
        if fallback_attempt > 0:
            if rotate:
                attempt_proxy = isolated_proxy(proxy)
                fallback_common = replace_proxy(common, attempt_proxy)
                ytdlp_args = (
                    f"--impersonate chrome:windows-10 -f {video_format} "
                    f"--socket-timeout {socket_timeout} "
                    "--add-headers \"Referer: https://www.tiktok.com/\" "
                    "--add-headers \"Accept-Language: en-US,en;q=0.9\""
                )
                if attempt_proxy:
                    ytdlp_args += f" --proxy {attempt_proxy}"
                fallback = [
                    "--option", "extractor.tiktok.posts.ytdl=true",
                    "--option", "extractor.tiktok.posts.module=yt_dlp",
                    "--option", f"extractor.tiktok.posts.cmdline-args={ytdlp_args}",
                ]
            delay = retry_delay(fallback_attempt - 1, base_delay)
            print(
                f"tiktok-dl: yt-dlp retry {fallback_attempt + 1}/{attempts} in {delay:g}s",
                file=sys.stderr,
            )
            time.sleep(delay)
        last_rc, _, counts, profile_failed, failure_kind = run(
            [binary, *fallback_common, *fallback, *extra, url], queue, url, manifest,
            media_delay=media_delay, new_items=remaining_quota(),
            failure_budget=failure_budget,
        )
        add_counts(totals, counts)
        if not profile_failed:
            break
    effective_rc = 1 if profile_failed and last_rc == 0 else last_rc
    # Profile extraction can fail before gallery-dl discovers any post ID.
    # Count that scan failure without inventing a media ID or queue entry.
    if effective_rc != 0 and not any(totals.values()):
        totals["FAILED"] = 1
    return effective_rc, totals, "yt-dlp"


def profile_name(target):
    match = re.search(r"(?:tiktok\.com/)?@([A-Za-z0-9._-]+)", target)
    if match:
        return match.group(1)
    if not target.startswith(("http://", "https://")):
        return target.lstrip("@")
    return None


def normalize_batch_target(value, line_number):
    if not value.startswith("-") and re.fullmatch(r"@?[A-Za-z0-9._-]+", value):
        return value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme in ("http", "https") and (host == "tiktok.com" or host.endswith(".tiktok.com")):
        return value
    raise ValueError(
        f"invalid target on line {line_number}; expected username, @username, or TikTok URL"
    )


def read_target_file(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"target file does not exist: {path}")
    targets = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read target file: {path}: {error}") from error
    for line_number, raw in enumerate(lines, 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        targets.append(normalize_batch_target(value, line_number))
    if not targets:
        raise ValueError(f"target file contains no targets: {path}")
    return targets


def eligible_queue_ids(queue, url, include_unscoped):
    return [
        video_id for video_id, record in queue.items()
        if record.get("target") == url or (include_unscoped and not record.get("target"))
    ]


def execute_target(target, extra, include_unscoped=True, new_items=None):
    if target.startswith(("http://", "https://")):
        url = target
    else:
        # Use /posts sub-path to activate TiktokPostsExtractor directly,
        # bypassing TiktokUserExtractor which also dispatches TiktokAvatarExtractor.
        # The avatar extractor makes urllib3 requests to TikTok's profile page
        # which 403, burning through the retryable-failure budget before posts
        # can even start.
        url = f"https://www.tiktok.com/@{target.lstrip('@')}/posts"

    try:
        proxy = proxy_url()
        media_delay = parse_media_delay(os.environ.get("MEDIA_DELAY", ""))
    except ValueError as error:
        print(f"tiktok-dl: configuration error: {error}", file=sys.stderr)
        return 2, {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 1}, "none"

    verbose = os.environ.get("GALLERY_DL_VERBOSE", "").lower() in ("1", "true", "yes")
    common = [
        "--destination", str(DOWNLOADS),
        "--download-archive", str(ARCHIVE),
        "--sleep-request", os.environ.get("SLEEP_REQUEST", "2-5"),
        *(["--verbose"] if verbose else []),
        *status_options(),
    ]
    # Route video/audio extraction through yt-dlp so curl-cffi can present a
    # real Chrome TLS fingerprint. gallery-dl's own urllib3 requests get 403
    # on video URLs because TikTok's WAF inspects the JA3/JA4 fingerprint.
    # VIDEO_FORMAT lets the user pick a specific format/quality; defaults to
    # yt-dlp's "best" (highest resolution available).
    # Use an isolated Tor identity if rotation is enabled.
    effective_proxy = proxy
    if tor_rotation_enabled(proxy):
        effective_proxy = isolated_proxy(proxy)
    video_format = os.environ.get("VIDEO_FORMAT", "best")
    # No --download-archive for yt-dlp: gallery-dl's own SQLite archive
    # deduplicates. Passing --download-archive to yt-dlp caused it to mutate
    # info_dict during process_info() in ways that triggered AttributeError
    # in gallery-dl's dispatch path.
    ytdlp_cmdline = f"--impersonate chrome -f {video_format} --socket-timeout 30"
    if effective_proxy:
        ytdlp_cmdline += f" --proxy {effective_proxy}"
    common.extend([
        # Route video extraction through yt-dlp so curl-cffi can present a
        # real Chrome TLS fingerprint. TikTok's WAF inspects JA3/JA4.
        # Audio is NOT routed through yt-dlp: music/audio files are served
        # from CDN URLs that don't require the TLS fingerprint bypass, and
        # routing audio through yt-dlp caused AttributeError crashes.
        "--option", "extractor.tiktok.videos=ytdl",
        # Delegate profile enumeration to yt-dlp (curl-cffi) so TikTok's WAF
        # sees a real Chrome TLS fingerprint instead of gallery-dl's urllib3.
        "--option", "extractor.tiktok.posts.ytdl=true",
        "--option", "extractor.tiktok.posts.module=yt_dlp",
        "--option", f"ytdl.cmdline-args={ytdlp_cmdline}",
    ])
    if effective_proxy:
        common[:0] = ["--proxy", effective_proxy]
    # Try multiple cookie file locations: env var > mounted > baked-in
    cookies = os.environ.get("COOKIES_FILE")
    if not cookies or not Path(cookies).is_file():
        cookies = "/cookies/cookies.txt"
    if not Path(cookies).is_file():
        cookies = "/cookiejar/tiktok-cookies.txt"
    if Path(cookies).is_file():
        common[:0] = ["--cookies", cookies]

    binary = os.environ.get("GALLERY_DL_BIN", "gallery-dl")
    manifest = ManifestStore()
    try:
        manifest.records()
    except ValueError as error:
        print(f"tiktok-dl: {error}", file=sys.stderr)
        return 2, {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 1}, "none"
    queue = load()
    primary_rc, totals, profile_backend = run_profile(
        binary, common, extra, url, queue, proxy, manifest, media_delay, new_items
    )

    username = profile_name(target)
    max_attempts = max(0, int(os.environ.get("RETRY_MAX_ATTEMPTS", "4")))
    base_delay = max(0.0, float(os.environ.get("RETRY_BASE_DELAY", "5")))

    eligible = eligible_queue_ids(queue, url, include_unscoped)
    if eligible and not username:
        print("tiktok-dl: cannot build retry URLs from this target; queue retained", file=sys.stderr)
    elif eligible:
        print(f"tiktok-dl: retrying {len(eligible)} queued video(s)", file=sys.stderr)

    for video_id in eligible:
        if new_items is not None and totals["DOWNLOADED"] >= new_items:
            break
        record = queue[video_id]
        attempts = int(record.get("attempts", 0))
        while attempts < max_attempts:
            delay = retry_delay(attempts, base_delay)
            print(f"tiktok-dl: retry {attempts + 1}/{max_attempts} for {video_id} in {delay:g}s", file=sys.stderr)
            time.sleep(delay)
            retry_token = "ZS-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14))
            retry_url = f"https://www.tiktok.com/@{username}/video/{video_id}?_r=1&_t={retry_token}"
            retry_common = replace_proxy(common, proxy)
            rc, failed, retry_counts, _, failure_kind = run(
                [binary, *retry_common, *extra, retry_url], queue, url, manifest,
                media_delay=media_delay,
                new_items=None if new_items is None else new_items - totals["DOWNLOADED"],
            )
            add_counts(totals, retry_counts)
            if rc == 0 and video_id not in failed:
                queue.pop(video_id, None)
                save(queue)
                print(f"tiktok-dl: retry succeeded for {video_id}", file=sys.stderr)
                break
            attempts += 1
            if tor_rotation_enabled(proxy) and failure_kind == "retryable":
                proxy = isolated_proxy(proxy)
            queue.setdefault(video_id, {})["attempts"] = attempts
            save(queue)
        else:
            print(f"tiktok-dl: retry limit reached for {video_id}; retained in {QUEUE}", file=sys.stderr)

    pending = len(eligible_queue_ids(queue, url, include_unscoped))
    quota_satisfied = new_items is not None and totals["DOWNLOADED"] >= new_items
    exit_code = primary_rc if primary_rc else (1 if pending and not quota_satisfied else 0)
    result = "OK" if exit_code == 0 else "FAILED"
    print(
        f"[SUMMARY] downloaded={totals['DOWNLOADED']} "
        f"skipped={totals['SKIPPED']} failed={totals['FAILED']} "
        f"pending={pending} result={result}",
        flush=True,
    )
    print(f"[BACKEND] profile={profile_backend}", flush=True)
    return exit_code, totals, profile_backend


def run_batch(targets, extra, new_items=None):
    totals = {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 0}
    failed_targets = 0
    for index, target in enumerate(targets, 1):
        print(f"[BATCH] target={index}/{len(targets)}")
        if new_items is None:
            rc, target_totals, _ = execute_target(target, extra, include_unscoped=False)
        else:
            rc, target_totals, _ = execute_target(
                target, extra, include_unscoped=False, new_items=new_items
            )
        add_counts(totals, target_totals)
        if rc:
            failed_targets += 1
    succeeded = len(targets) - failed_targets
    result = "FAILED" if failed_targets else "OK"
    print(
        f"[BATCH SUMMARY] targets={len(targets)} succeeded={succeeded} "
        f"failed_targets={failed_targets} downloaded={totals['DOWNLOADED']} "
        f"skipped={totals['SKIPPED']} failed={totals['FAILED']} result={result}",
        flush=True,
    )
    return 1 if failed_targets else 0


def open_archive(write=False):
    if not ARCHIVE.is_file():
        raise ValueError(f"download archive does not exist: {ARCHIVE}")
    try:
        if write:
            connection = sqlite3.connect(ARCHIVE, timeout=60)
        else:
            connection = sqlite3.connect(ARCHIVE.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
        columns = connection.execute("PRAGMA table_info(archive)").fetchall()
        expected = len(columns) == 1 and columns[0][1] == "entry" and columns[0][2].upper() == "TEXT" and columns[0][5] == 1
        if not expected:
            connection.close()
            raise ValueError("download archive has an unexpected schema; expected archive(entry TEXT PRIMARY KEY)")
        return connection
    except sqlite3.Error as error:
        raise ValueError(f"cannot open download archive safely: {error}") from error


def history_entries(connection):
    videos = {}
    for (entry,) in connection.execute("SELECT entry FROM archive ORDER BY entry"):
        match = re.match(r"^tiktok(\d+)_", entry)
        if match:
            video_id = match.group(1)
            videos[video_id] = videos.get(video_id, 0) + 1
    return videos


def history_command(args):
    if not args or args[0] not in ("list", "remove", "clear"):
        print("tiktok-dl: usage: history list [--json] | history remove VIDEO_ID | history clear --yes", file=sys.stderr)
        return 2
    action, *options = args
    if action == "remove" and (len(options) != 1 or not re.fullmatch(r"\d{10,}", options[0])):
        print("tiktok-dl: history remove requires one numeric VIDEO_ID", file=sys.stderr)
        return 2
    if action == "clear" and options != ["--yes"]:
        print("tiktok-dl: history clear is destructive; repeat with --yes", file=sys.stderr)
        return 2
    if action == "list" and any(option != "--json" for option in options):
        print("tiktok-dl: history list accepts only --json", file=sys.stderr)
        return 2

    connection = None
    try:
        connection = open_archive(write=action != "list")
        if action == "list":
            videos = history_entries(connection)
            if "--json" in options:
                print(json.dumps([
                    {"video_id": video_id, "records": count}
                    for video_id, count in videos.items()
                ], sort_keys=True))
            elif not videos:
                print("history: archive is empty")
            else:
                for video_id, count in videos.items():
                    print(f"{video_id} records={count}")
            return 0
        if action == "remove":
            video_id = options[0]
            with connection:
                cursor = connection.execute(
                    "DELETE FROM archive WHERE entry GLOB ?", (f"tiktok{video_id}_*",)
                )
            if cursor.rowcount == 0:
                print(f"history: no archive records matched video {video_id}")
                return 1
            print(f"history: removed {cursor.rowcount} archive record(s) for video {video_id}")
            return 0
        with connection:
            cursor = connection.execute("DELETE FROM archive")
        print(f"history: cleared {cursor.rowcount} archive record(s); archive file preserved")
        return 0
    except ValueError as error:
        print(f"tiktok-dl: {error}", file=sys.stderr)
        return 2
    except sqlite3.Error as error:
        print(f"tiktok-dl: archive operation failed atomically: {error}", file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            connection.close()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 2
    if args[0] == "history":
        return history_command(args[1:])
    if args[0] == "from-file":
        if len(args) < 2:
            print("tiktok-dl: from-file requires a file path", file=sys.stderr)
            return 2
        path, extra = args[1], args[2:]
    elif args[0] == "--from-file":
        if len(args) < 2:
            print("tiktok-dl: --from-file requires a file path", file=sys.stderr)
            return 2
        path, extra = args[1], args[2:]
    else:
        try:
            extra, new_items = parse_new_items(args[1:])
        except ValueError as error:
            print(f"tiktok-dl: {error}", file=sys.stderr)
            return 2
        if new_items is None:
            rc, _, _ = execute_target(args[0], extra)
        else:
            rc, _, _ = execute_target(args[0], extra, new_items=new_items)
        return rc
    try:
        extra, new_items = parse_new_items(extra)
    except ValueError as error:
        print(f"tiktok-dl: {error}", file=sys.stderr)
        return 2
    try:
        targets = read_target_file(path)
    except ValueError as error:
        print(f"tiktok-dl: {error}", file=sys.stderr)
        return 2
    if new_items is None:
        return run_batch(targets, extra)
    return run_batch(targets, extra, new_items=new_items)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ntiktok-dl: interrupted; retry queue was preserved", file=sys.stderr)
        raise SystemExit(130)
