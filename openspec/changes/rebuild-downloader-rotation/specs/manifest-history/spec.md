# Delta: manifest-history

## MODIFIED Requirements

### Requirement: Per-Item Status Tracking (was implicit end-of-profile)

**Previously**: Status written once per profile after all items completed.

**MUST** now track each video's status independently: `downloaded`, `skipped`, `failed`.

### Requirement: Mid-Cycle Manifest Writes

**Previously**: Manifest updated only after full profile finished.

**MUST** write manifest status immediately after each item's outcome.

### Requirement: Skip Already-Downloaded Items (new atomic behavior)

Pipeline SHALL check manifest status before attempting download; if already `downloaded`, mark `skipped`.

## REMOVED Requirements (from previous design)

### Requirement: End-of-Profile Status Write

(Deprecated: batch write after all items completed)

## RENAMED Requirements

None