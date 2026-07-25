#!/usr/bin/env python3
# Merge per-sheet region JSONs (matrix job artifacts) into the single
# dataregions.json that finalize.py consumes. Every sheet in charts.txt
# must be present — a missing region is a hard failure, never a hole.
import glob
import json
import sys

out = {}
for path in sorted(glob.glob(sys.argv[1] + "/**/*.json", recursive=True)):
    out.update(json.load(open(path)))

charts = [
    line.strip()
    for line in open("/repo/charts.txt")
    if line.strip() and not line.startswith("#")
]
missing = [c for c in charts if c not in out]
if missing:
    raise SystemExit(f"missing regions: {missing}")

json.dump(out, open("/repo/data/conus/dataregions.json", "w"))
print("merged", len(out), "regions")
