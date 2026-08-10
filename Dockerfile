# syntax=docker/dockerfile:1.7

FROM python:3.14-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        "gallery-dl[default]" \
        "yt-dlp[default,curl-cffi]" \
        PySocks \
    && python3 -c "import curl_cffi; print('curl_cffi', curl_cffi.__version__)"

# Patch gallery-dl: filter out False entries from yt-dlp results that cause
# AttributeError: 'bool' object has no attribute 'get' (upstream bug).
RUN python3 -c "\
import pathlib; \
p = pathlib.Path('/usr/local/lib/python3.14/site-packages/gallery_dl/extractor/tiktok.py'); \
s = p.read_text(); \
old = 'return [video[\"url\"].partition(\"?\")[0]\n                    for video in info_dict[\"entries\"]]'; \
new = 'return [video[\"url\"].partition(\"?\")[0]\n                    for video in info_dict[\"entries\"] if isinstance(video, dict)]'; \
p.write_text(s.replace(old, new)); \
print('patched' if new in p.read_text() else 'PATCH FAILED') \
"

COPY docker-entrypoint.sh /usr/local/bin/tiktok-dl
COPY retry_runner.py /usr/local/lib/tiktok-dl/retry_runner.py
COPY tiktok-cookies.txt /cookiejar/tiktok-cookies.txt
RUN sed -i 's/\r$//' /usr/local/bin/tiktok-dl \
    && chmod +x /usr/local/bin/tiktok-dl \
    && mkdir -p /downloads

WORKDIR /downloads
VOLUME ["/downloads"]

ENTRYPOINT ["tiktok-dl"]