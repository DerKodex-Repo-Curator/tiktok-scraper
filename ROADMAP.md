# Roadmap

The current priority is an operable, manually released Docker downloader. CI/CD
is intentionally out of scope for this milestone.

## Delivered

- [x] gallery-dl and yt-dlp forks pinned and SHA-verified during build.
- [x] BuildKit secret for the private gallery-dl fork.
- [x] Single-target and sequential `from-file` operation.
- [x] SQLite incremental archive and guarded history commands.
- [x] Persistent target-scoped retry queue.
- [x] gallery-dl native extraction with yt-dlp/curl-cffi fallback.
- [x] SOCKS5H support and failure-triggered Tor `IsolateSOCKSAuth` rotation.
- [x] Deduplicated JSON and deterministic CSV manifests.
- [x] Optional random inter-media pacing independent of request/retry delays.
- [x] Archive-aware `--new-items` quota for single and sequential batch targets.
- [x] Unit tests plus documented manual smoke tests.
- [x] Quick-start, architecture, operations, and troubleshooting documentation.

## Next

- [ ] Run and record the complete Docker/Tor smoke-test checklist from WSL.
- [ ] Publish a manually tagged image only after smoke tests pass.
- [ ] Record published image digest and pinned fork SHAs with each manual release.
- [ ] Decide whether transitive Python dependencies need a reviewed lock or wheel
      checksum policy beyond the existing application-source pins.
- [ ] Define retention and backup policy for `/downloads` state.

## Not planned for this milestone

- CI/CD or automated registry publication.
- Restoring the archived Node.js CLI, module API, hashtag/trend/music commands,
  or its JSON history format.
- Concurrent batch workers; sequential processing protects archive, retry, and
  Tor-attempt ownership.
- Adding FFmpeg; the current download and pacing path does not require it.
