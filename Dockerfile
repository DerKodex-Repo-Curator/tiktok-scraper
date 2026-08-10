# syntax=docker/dockerfile:1.7

FROM python:3.14-slim AS sources

ARG GALLERY_DL_REPOSITORY=https://github.com/DerKodex-Repo-Curator/gallery-dl-official.git
ARG GALLERY_DL_REF=1b68ec56f35651753c4fc527685f56f3a1bd63ee
ARG YT_DLP_REPOSITORY=https://github.com/DerKodex-Repo-Curator/yt-dlp.git
ARG YT_DLP_REF=5d6b8c8cd19785c3086ae3a9ec618c45e25eb3bc

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# The token exists only as an in-memory BuildKit secret for this instruction.
# It is never placed in an ARG, ENV, repository URL, or resulting layer.
RUN --mount=type=secret,id=github_token,required=true \
    set -eu; \
    token="$(cat /run/secrets/github_token)"; \
    test -n "$token"; \
    auth="$(printf 'x-access-token:%s' "$token" | base64 | tr -d '\n')"; \
    git init gallery-dl; \
    git -C gallery-dl -c "http.extraHeader=Authorization: Basic ${auth}" \
        fetch --depth 1 "$GALLERY_DL_REPOSITORY" "$GALLERY_DL_REF"; \
    git -C gallery-dl checkout --detach FETCH_HEAD; \
    test "$(git -C gallery-dl rev-parse HEAD)" = "$GALLERY_DL_REF"; \
    rm -rf gallery-dl/.git; \
    unset auth token

RUN set -eu; \
    git init yt-dlp; \
    git -C yt-dlp fetch --depth 1 "$YT_DLP_REPOSITORY" "$YT_DLP_REF"; \
    git -C yt-dlp checkout --detach FETCH_HEAD; \
    test "$(git -C yt-dlp rev-parse HEAD)" = "$YT_DLP_REF"; \
    rm -rf yt-dlp/.git

FROM python:3.14-slim AS wheels

COPY --from=sources /src/gallery-dl /src/gallery-dl
COPY --from=sources /src/yt-dlp /src/yt-dlp
RUN pip wheel --no-cache-dir --wheel-dir /wheels \
    /src/gallery-dl \
    "/src/yt-dlp[default,curl-cffi]" \
    PySocks

FROM python:3.14-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
        gallery-dl yt-dlp PySocks \
    && rm -rf /wheels

COPY docker-entrypoint.sh /usr/local/bin/tiktok-dl
COPY retry_runner.py /usr/local/lib/tiktok-dl/retry_runner.py
RUN sed -i 's/\r$//' /usr/local/bin/tiktok-dl \
    && chmod +x /usr/local/bin/tiktok-dl \
    && mkdir -p /downloads

WORKDIR /downloads
VOLUME ["/downloads"]

ENTRYPOINT ["tiktok-dl"]
