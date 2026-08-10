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
# 1. Wrap _extract_posts_ytdl's yt-dlp call in try/except so any AttributeError
#    from yt-dlp's internal processing of archived/False entries is caught and
#    logged instead of propagating to Job.run() as "An unexpected error occurred".
#    Also filters out any remaining False entries from info_dict["entries"].
# 2. When ytdl=true and _extract_posts_ytdl returns empty, do NOT fall back
#    to _extract_posts_api (urllib3) which 403s and crashes. Return empty.
# 3. Guard _check_status_code against non-dict detail (False from failed
#    rehydration data extraction).
# 4+5 already covered by prior patch labels above (renaming to avoid confusion).
# 5. When _extract_rehydration_data fails (TikTok WAF 403 on individual video
#    pages) and videos=ytdl, build a minimal post dict from the URL and yield
#    it directly to the yt-dlp downloader, bypassing urllib3 entirely.
RUN python3 -c "\
import pathlib; \
p = pathlib.Path('/usr/local/lib/python3.14/site-packages/gallery_dl/extractor/tiktok.py'); \
s = p.read_text(); \
old1 = '        with ytdl_instance as ydl:\n            info_dict = ydl._YoutubeDL__extract_info(\n                profile_url, ydl.get_info_extractor(\"TikTokUser\"),\n                False, {}, True)\n            # This should be a list of video and photo post URLs in /video/\n            # format.\n            return [video[\"url\"].partition(\"?\")[0]\n                    for video in info_dict[\"entries\"]]'; \
new1 = '        try:\n            with ytdl_instance as ydl:\n                info_dict = ydl._YoutubeDL__extract_info(\n                    profile_url, ydl.get_info_extractor(\"TikTokUser\"),\n                    False, {}, True)\n                return [video[\"url\"].partition(\"?\")[0]\n                        for video in info_dict[\"entries\"]\n                        if isinstance(video, dict)]\n        except (AttributeError, TypeError) as exc:\n            self.log.error(\"yt-dlp profile extraction failed: %s\", exc)\n            self.log.traceback(exc)\n            return []'; \
s = s.replace(old1, new1); \
old2 = '        if posts := self._extract_posts_api(profile_url, user_name):\n            return posts'; \
new2 = '        if not ytdl:\n            if posts := self._extract_posts_api(profile_url, user_name):\n                return posts'; \
s = s.replace(old2, new2); \
old3 = '    def _check_status_code(self, detail, url, type_of_url):\n        status = detail.get(\"statusCode\")'; \
new3 = '    def _check_status_code(self, detail, url, type_of_url):\n        if not isinstance(detail, dict):\n            return False\n        status = detail.get(\"statusCode\")'; \
s = s.replace(old3, new3); \
old5 = '                data = self._extract_rehydration_data(tiktok_url)\n                if \"webapp.video-detail\" not in data:\n                    # Only /video/ links result in the video-detail dict we\n                    # need. Try again using that form of link.\n                    tiktok_url = self._sanitize_url(\n                        data[\"seo.abtest\"][\"canonical\"])\n                    data = self._extract_rehydration_data(tiktok_url)\n                video_detail = data[\"webapp.video-detail\"]\n                if not self._check_status_code(\n                        video_detail, tiktok_url, \"post\"):\n                    continue\n                post = video_detail[\"itemInfo\"][\"itemStruct\"]'; \
new5 = '                try:\n                    data = self._extract_rehydration_data(tiktok_url)\n                    if \"webapp.video-detail\" not in data:\n                        tiktok_url = self._sanitize_url(\n                            data[\"seo.abtest\"][\"canonical\"])\n                        data = self._extract_rehydration_data(tiktok_url)\n                    video_detail = data[\"webapp.video-detail\"]\n                    if not self._check_status_code(\n                            video_detail, tiktok_url, \"post\"):\n                        continue\n                    post = video_detail[\"itemInfo\"][\"itemStruct\"]\n                except Exception as _reh_exc:\n                    if self.video != \"ytdl\":\n                        raise\n                    import re as _re_ytdl\n                    _vid = _re_ytdl.search(r\"/video/(\\d+)\", tiktok_url)\n                    if not _vid:\n                        raise\n                    _vid_id = int(_vid.group(1))\n                    _uname = tiktok_url.split(\"/@\")[1].split(\"/\")[0]\n                    self.log.warning(\n                        \"%s: rehydration failed (%s), routing to yt-dlp\",\n                        tiktok_url, _reh_exc.__class__.__name__)\n                    post = {\n                        \"id\": _vid_id, \"desc\": \"\", \"createTime\": 0,\n                        \"author\": {\"uniqueId\": _uname}, \"user\": _uname,\n                        \"date\": self.parse_timestamp(0), \"post_type\": \"video\",\n                        \"filename\": \"\", \"extension\": \"mp4\",\n                        \"title\": \"\", \"type\": \"video\", \"num\": 0,\n                        \"file_id\": \"\", \"width\": 0, \"height\": 0,\n                        \"image\": None,\n                    }\n                    yield Message.Directory, \"\", post\n                    yield Message.Url, \"ytdl:\" + tiktok_url, post\n                    continue'; \
s = s.replace(old5, new5); \
p.write_text(s); \
t = p.read_text(); \
ok1 = 'if isinstance(video, dict)' in t; \
ok2 = 'if not ytdl:' in t; \
ok3 = 'not isinstance(detail, dict)' in t; \
ok4 = 'except (AttributeError, TypeError) as exc' in t; \
ok5 = 'routing to yt-dlp' in t; \
print(f'patches: filter={ok1} api={ok2} status={ok3} ytdl_guard={ok4} reh_fallback={ok5}'); \
assert ok1 and ok2 and ok3 and ok4 and ok5, 'gallery-dl patch failed - check string alignment with installed version' \
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