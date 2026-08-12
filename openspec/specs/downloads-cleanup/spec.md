# `downloads-cleanup` Spec

## Purpose

Ensure clean state for test runs (full wipe) vs completed runs (remove leftovers only).

## Requirements

### Requirement: Test Mode Cleanup

`clean_downloads(mode=test)` MUST remove all contents of `downloads/` folder.

#### Scenario: Full wipe before test run

- GIVEN `downloads/` contains `.part`, `.mp4`, `.image`
- WHEN `clean_downloads(mode=test)` runs
- THEN all files removed; folder empty

### Requirement: Final Mode Cleanup

`clean_downloads(mode=final)` MUST remove only `.part` and `.image` files.

#### Scenario: Leftover removal preserves final files

- GIVEN `downloads/` contains `final.mp4`, `stale.part`, `stale.image`
- WHEN `clean_downloads(mode=final)` runs
- THEN `final.mp4` retained; only `.part`/`.image` removed

### Requirement: Safe Handling of Missing Folder

Cleanup MUST NOT raise error if `downloads/` is missing.

#### Scenario: Folder absent during final cleanup

- GIVEN `downloads/` deleted externally
- WHEN `clean_downloads(mode=final)` called
- THEN returns success without exception