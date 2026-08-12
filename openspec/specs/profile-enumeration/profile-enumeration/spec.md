# Delta: profile-enumeration

## MODIFIED Requirements

### Requirement: Separate Enumeration from Download (was bundled)

**Previously**: `download_profile()` enumerated items and downloaded within same loop.

**MUST** now separate `enumerate_profile()` from `download_pipeline()`.

### Requirement: Paginated, Resumable Enumeration (new)

Enumeration MUST return items page-by-page with cursor support.

### Requirement: Per-Item Proxy Rotation Enumeration

Each pagination call receives fresh proxy URL; items within page share same rotation.

## REMOVED Requirements (from previous design)

### Requirement: Inline Enumeration Within Download Loop

(Deprecated: item list generated and consumed within single profile download)

## RENAMED Requirements

None