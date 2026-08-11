# tiktok-docker Specification

## Purpose
Docker image that runs tiktok-dl without local installation, using yt-dlp
with curl-cffi for TLS impersonation.

## Requirements

### Requirement: Base Image and Dependencies
The image MUST be built on `python:3.14-slim` and install `yt-dlp[default,curl-cffi]` and `PySocks`.

#### Scenario: Image Build
- GIVEN Docker is installed
- WHEN building the image with `docker build -t tiktok-dl .`
- THEN the image includes yt-dlp with curl-cffi and PySocks
- AND no gallery-dl dependency is present

### Requirement: Cookies Mounting
The container MUST allow mounting a cookies file at `/cookiejar/tiktok-cookies.txt`.

#### Scenario: Use Mounted Cookies
- GIVEN a user provides a Netscape cookies file
- WHEN running `docker run -v /path/to/cookies.txt:/cookiejar/tiktok-cookies.txt tiktok-dl USERNAME`
- THEN the download uses the provided cookies for authentication

### Requirement: Persistent Downloads Volume
The container MUST expose a volume at `/downloads` for persistent storage.

#### Scenario: Persistent Storage
- GIVEN a host directory `/host/downloads`
- WHEN running `docker run -v /host/downloads:/downloads tiktok-dl USERNAME`
- THEN downloaded videos are stored in `/downloads/{username}` on the host
- AND manifests persist across container restarts

### Requirement: Environment Variable Configuration
The container MUST accept all CLI environment variables (SOCKS_PROXY_URL, COOKIES_FILE, VIDEO_FORMAT, etc.).

#### Scenario: Configure Proxy in Container
- GIVEN `SOCKS_PROXY_URL` is set
- WHEN running `docker run -e SOCKS_PROXY_URL=socks5h://host:9050 tiktok-dl USERNAME`
- THEN yt-dlp uses the specified proxy for all requests