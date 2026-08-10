# syntax=docker/dockerfile:1.7

FROM python:3.14-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    TIKTOK_FORCE_FALLBACK=true \
    PROFILE_TIMEOUT=45

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        "gallery-dl[default]==1.32.9" \
        "yt-dlp[default,curl-cffi]" \
        PySocks \
    && python3 -c "import curl_cffi; print('curl_cffi', curl_cffi.__version__)"

# Patch gallery-dl:
# 1. Filter out False entries from yt-dlp results that cause
#    AttributeError: 'bool' object has no attribute 'get' (upstream bug).
# 2. When ytdl=true and _extract_posts_ytdl returns empty, do NOT fall back
#    to _extract_posts_api (urllib3) which 403s and crashes. Return empty.
# 3. Guard _check_status_code against non-dict detail (False from failed
#    rehydration data extraction).
RUN python3 -c "\
import pathlib; \
p = pathlib.Path('/usr/local/lib/python3.14/site-packages/gallery_dl/extractor/tiktok.py'); \
s = p.read_text(); \
old1 = 'return [video[\"url\"].partition(\"?\")[0]\n                    for video in info_dict[\"entries\"]]'; \
new1 = 'return [video[\"url\"].partition(\"?\")[0]\n                    for video in info_dict[\"entries\"] if isinstance(video, dict)]'; \
s = s.replace(old1, new1); \
old2 = '        if posts := self._extract_posts_api(profile_url, user_name):\n            return posts'; \
new2 = '        if not ytdl:\n            if posts := self._extract_posts_api(profile_url, user_name):\n                return posts'; \
s = s.replace(old2, new2); \
old3 = '    def _check_status_code(self, detail, url, type_of_url):\n        status = detail.get(\"statusCode\")'; \
new3 = '    def _check_status_code(self, detail, url, type_of_url):\n        if not isinstance(detail, dict):\n            return False\n        status = detail.get(\"statusCode\")'; \
s = s.replace(old3, new3); \
p.write_text(s); \
t = p.read_text(); \
ok1 = 'if isinstance(video, dict)' in t; \
ok2 = 'if not ytdl:' in t; \
ok3 = 'not isinstance(detail, dict)' in t; \
print(f'patches: bool={ok1} api={ok2} status={ok3}'); \
assert ok1 and ok2 and ok3, 'gallery-dl patch failed - check string alignment with installed version' \
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