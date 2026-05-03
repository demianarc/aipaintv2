"""Refresh data/met_painting_ids.json from the Met API."""

import json
import os
import urllib.request

BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
DEPTS = (11, 21)  # European Paintings, American Paintings
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "met_painting_ids.json")


def main():
    ids: set[int] = set()
    for dept in DEPTS:
        url = f"{BASE}/objects?departmentIds={dept}"
        with urllib.request.urlopen(url, timeout=30) as r:
            got = json.loads(r.read()).get("objectIDs") or []
        print(f"dept {dept}: {len(got)} ids")
        ids.update(got)
    out = sorted(ids)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f)
    print(f"wrote {len(out)} ids -> {OUT}")


if __name__ == "__main__":
    main()
