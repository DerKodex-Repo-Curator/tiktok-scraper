# tiktok-downloader-cli Specification

## Purpose
Python CLI binary that downloads TikTok profiles using yt-dlp with curl-cffi
TLS impersonation, SOCKS5 proxy support, and Netscape cookie authentication.

## Requirements

### Requirement: Download Single Video from URL
The system MUST download a single TikTok video when given a direct video URL.

#### Scenario: Download single video from URL
- GIVEN a valid TikTok video URL `https://www.tiktok.com/@user/video/123`
- WHEN the user runs `tiktok-dl URL`
- THEN the video is downloaded to `{downloads}/{username}/{video_id} {title}.mp4`
- AND the manifest is updated with the video record

### Requirement: Download Full Profile
The system MUST enumerate and download all videos from a TikTok profile.

#### Scenario: Download full profile
- GIVEN a valid TikTok username
- WHEN the user runs `tiktok-dl USERNAME`
- THEN yt-dlp enumerates all videos via `--flat-playlist`
- AND each video is downloaded sequentially with rate limiting

### Requirement: Download with Range Limit
The system MUST support limiting the number of videos downloaded.

#### Scenario: Download with --range limit
- GIVEN a username with multiple videos
- WHEN the user runs `tiktok-dl USERNAME --range 1`
- THEN only the most recent video is downloaded
- AND the manifest reflects only that video

### Requirement: Skip Already-Downloaded Videos
The system MUST skip videos present in the download archive.

#### Scenario: Skip already-downloaded videos
- GIVEN previously downloaded videos exist in the archive
- WHEN the user runs `tiktok-dl USERNAME --new-items 5`
- THEN only new videos beyond the archive count are downloaded
- AND archived videos are reported as SKIPPED

### Requirement: Batch Download from File
The system MUST accept a file with one username per line for batch processing.

#### Scenario: Batch download from file
- GIVEN a file `targets.txt` with one username per line
- WHEN the user runs `tiktok-dl from-file targets.txt`
- THEN each username is processed sequentially
- AND a batch summary is printed at the end

### Requirement: Proxy Rotation on Failure
The system MUST rotate Tor identity when a download fails with a retryable error.

#### Scenario: Proxy rotation on failure
- GIVEN `SOCKS_PROXY_URL` is set to a SOCKS5 proxy with Tor
- WHEN a download fails with 403 or timeout
- THEN a new isolated SOCKS identity is generated
- AND the next retry uses the new Tor circuit

### Requirement: Watchdog Timeout
The system MUST kill processes that produce no output for a configurable timeout.

#### Scenario: Watchdog timeout on hung process
- GIVEN `PROFILE_TIMEOUT` is set to 120 seconds
- WHEN a download process produces no output for 120s
- THEN the process is terminated
- AND the failure is recorded as retryable

### Requirement: Cookie-Based Authentication
The system MUST use Netscape-format cookies for TikTok authentication.

#### Scenario: Cookie-based authentication
- GIVEN a valid Netscape cookies file at `COOKIES_FILE`
- WHEN the user runs `tiktok-dl USERNAME`
- THEN yt-dlp receives the cookies via `--cookies`
- AND TikTok treats the request as an authenticated session