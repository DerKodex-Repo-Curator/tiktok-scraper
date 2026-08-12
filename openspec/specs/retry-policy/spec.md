# Delta: retry-policy

## MODIFIED Requirements

### Requirement: Per-Item Retry (was per-profile)

**Previously**: Profile-wide 120s watchdog enforced across all items; retries applied to whole profile, not individual items.

**MUST** now retry each video independently up to 5 attempts using jittered exponential backoff.

### Requirement: Jittered Exponential Backoff (was constant watchdog)

**Previously**: Fixed 120s interval per profile with no variation.

**MUST** implement jittered backoff: `backoff = base * (2 ** attempt) + random_jitter` where `base = 5s`, jitter ∈ [0, 2s].

### Requirement: Max 5 Retry Attempts (new constraint)

No cap existed previously; now MUST not exceed 5 attempts per video.

#### Scenario: Exactly 5 retries applied

- GIVEN video `v123` fails on initial attempt
- WHEN retries execute
- THEN exactly 4 additional attempts occur (total 5)
- THEN marks `failed` if all 5 fail

#### Scenario: Early success terminates retry

- GIVEN video `v123` succeeds on attempt 3
- WHEN subsequent attempts triggered
- THEN no further retries occur
- THEN marks `downloaded`

## REMOVED Requirements (from previous design)

### Requirement: Profile Watchdog

(Deprecated: 120s profile-level timeout with single retry scope)

## RENAMED Requirements

None