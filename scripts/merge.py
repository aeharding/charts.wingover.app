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
    for line in open(f"/repo/charts-{REGION}.txt")
    if line.strip() and not line.startswith("#")
]
missing = [c for c in charts if c not in out]
if missing:
    raise SystemExit(f"missing regions: {missing}")

os.makedirs(f"/repo/data/{REGION}", exist_ok=True)
json.dump(out, open(f"/repo/data/{REGION}/dataregions.json", "w"))
print("merged", len(out), "regions")
