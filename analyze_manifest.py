import json
from collections import Counter

with open("/tmp/manifest-finn-full.json") as f:
    d = json.load(f)

c = Counter(e.get("status", "unknown") for e in d)
print(f"total entries: {len(d)}")
print(f"status breakdown: {dict(c)}")
downloaded = [e for e in d if e.get("status") == "downloaded"]
paths = [e.get("path", "") for e in downloaded]
empty = [p for p in paths if not p]
print(f"downloaded: {len(downloaded)}")
print(f"downloaded with path: {len([p for p in paths if p])}")
print(f"downloaded without path: {len(empty)}")
failed = [e for e in d if e.get("status") == "failed"]
print(f"failed: {len(failed)}")
if failed:
    print("failed reasons:")
    for e in failed[:10]:
        vid = e.get("video_id")
        title = e.get("title", "")[:60]
        print(f"  {vid}: {title}")

print()
print("=== First 5 manifest entries ===")
for e in d[:5]:
    vid = e.get("video_id")
    status = e.get("status")
    path = e.get("path", "")[:80]
    print(f"{vid}: status={status}, path={path}")
print("...")
print("=== Last 5 manifest entries ===")
for e in d[-5:]:
    vid = e.get("video_id")
    status = e.get("status")
    path = e.get("path", "")[:80]
    print(f"{vid}: status={status}, path={path}")