"""Diff FAA's published sheet list against charts-*.txt.

FAA adds, renames and retires sheets between cycles — Houlton was
retired, and its absence went unnoticed because our chart lists are
hand-maintained. This fails the bake when the published set and our
lists disagree, so a new sheet cannot silently go unbaked (or a retired
one silently 404 the fetch).

Usage: python3 scripts/check-sheet-list.py <cycle MM-DD-YYYY>
"""

import json
import re
import sys
import urllib.request

CYCLE = sys.argv[1] if len(sys.argv) > 1 else "07-09-2026"
BASE = f"https://aeronav.faa.gov/visual/{CYCLE}"


def listing(path):
    req = urllib.request.Request(
        f"{BASE}/{path}/", headers={"User-Agent": "Mozilla/5.0"}
    )
    html = urllib.request.urlopen(req, timeout=120).read().decode("latin-1")
    return {
        m.rsplit("/", 1)[-1][:-4]
        for m in re.findall(r'HREF="([^"]+\.zip)"', html, re.I)
    }


published = listing("sectional-files") | listing("Caribbean")

ours = set()
for region in json.load(open("/repo/regions.json")):
    for line in open(f"/repo/charts-{region}.txt"):
        line = line.strip()
        if line and not line.startswith("#"):
            ours.add(line.split("::", 1)[0])

# Sheets we deliberately do not bake (documented in regions.json notes).
EXCLUDED = set()

missing = published - ours - EXCLUDED  # published but not in any list
stale = ours - published  # in our lists but no longer published

if missing or stale:
    print(f"SHEET LIST MISMATCH for cycle {CYCLE}")
    for m in sorted(missing):
        print(f"   NOT BAKED (published by FAA): {m}")
    for s in sorted(stale):
        print(f"   NO LONGER PUBLISHED (in our list): {s}")
    print("Update charts-<region>.txt, or add to EXCLUDED with a reason.")
    sys.exit(1)

print(f"sheet list OK: {len(ours)} sheets, matches FAA cycle {CYCLE}")
