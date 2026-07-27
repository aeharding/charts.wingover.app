
import os

# Repo root resolved from THIS FILE, never hardcoded: the CI plan job
# runs outside the container where /repo does not exist. bands.py
# failing there produced an EMPTY tile matrix, so every tile job
# skipped silently and the bake shipped only z0-7.
REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

#!/usr/bin/env python3
# Merge per-sheet region JSONs (matrix job artifacts) into the single
# dataregions.json that finalize.py consumes. Every sheet in the
# REGION's chart list
# must be present — a missing region is a hard failure, never a hole.
import glob
import json
import os
import sys


out = {}
for path in sorted(glob.glob(sys.argv[1] + "/**/*.json", recursive=True)):
    out.update(json.load(open(path)))

REGION = os.environ.get("REGION", "conus")
charts = [
    line.strip()
    for line in open(f"{REPO}/charts-{REGION}.txt")
    if line.strip() and not line.startswith("#")
]
missing = [c for c in charts if c not in out]
if missing:
    raise SystemExit(f"missing regions: {missing}")

os.makedirs(f"{REPO}/data/{REGION}", exist_ok=True)
json.dump(out, open(f"{REPO}/data/{REGION}/dataregions.json", "w"))
print("merged", len(out), "regions")
