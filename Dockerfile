# Multi-stage Dockerfile for tiktok-dl
# Builder installs yt-dlp + curl-cffi + PySocks; runtime is minimal.

# ---------------------------------------------------------------------------
# Stage 1: Builder
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS builder

WORKDIR /build

# Install build deps for curl-cffi (needs a C compiler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
COPY src/ ./src/
COPY api/ ./api/

# Install into a prefix we can copy to runtime
RUN pip install --no-cache-dir --prefix=/install \
    "yt-dlp[default,curl-cffi]>=2024.0.0" \
    "PySocks>=1.7" \
    "fastapi>=0.110" \
    "uvicorn>=0.30" \
    "pydantic>=2.5" \
    "jinja2>=3.1" \
    "python-multipart>=0.0.9" \
    "pillow>=10.0" \
    .

# ---------------------------------------------------------------------------
# Stage 2: Runtime
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

LABEL org.opencontainers.image.title="tiktok-dl" \
      org.opencontainers.image.description="TikTok downloader using yt-dlp with SOCKS5 + Tor rotation." \
      org.opencontainers.image.version="0.1.0"

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create working directories for downloads, cookies, and config
WORKDIR /app
RUN mkdir -p /downloads /cookies /config

# Copy application source (for non-installed files like templates/static)
COPY api/ ./api/
COPY ui/ ./ui/
COPY src/ ./src/

# Environment defaults (overridable at runtime)
ENV PROXY_URL="socks5h://proxyto.hs.sof.ar:9050" \
    COOKIE_FILE="/cookies/cookies.txt" \
    VIDEO_FORMAT="best" \
    PROFILE_TIMEOUT="120" \
    PROFILE_MAX_ATTEMPTS="3" \
    SLEEP_REQUEST="2-5" \
    PYTHONUNBUFFERED="1"

# Volume mount points
VOLUME ["/downloads", "/cookies", "/config"]

# Expose API port
EXPOSE 8000

# Health check: hit the API health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health').read()" || exit 1

# Default: run the API server. Override with: docker run ... tiktok-dl @username
ENTRYPOINT ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]