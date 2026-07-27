
import os

# Repo root resolved from THIS FILE, never hardcoded: the CI plan job
# runs outside the container where /repo does not exist. bands.py
# failing there produced an EMPTY tile matrix, so every tile job
# skipped silently and the bake shipped only z0-7.
REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

#!/usr/bin/env python3
# Emit the tile-matrix shards as JSON: longitude bands aligned to z8
# tile columns in EPSG:3857, so band edges never split a tile and each
# shard's z8-12 pyramid is complete and disjoint.
import json
import math
import os
import sys


TILE0 = 20037508.342789244
Z8 = 2 * TILE0 / 256  # z8 tile width in meters
# Longitude span comes from the region's grid (regions.json): each
# region tiles its own extent, so one bake covers everything from the
# Aleutians to Puerto Rico.
REGION = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REGION", "conus")
_grid = json.load(open(f"{REPO}/regions.json"))[REGION]["grid"]
WEST, EAST = _grid[0] - 0.5, _grid[2] + 0.5
COLS_PER_BAND = 3

def col(lon):
    return (lon + 180.0) / 360.0 * 256

# Clamp to the z8 grid. The half-degree padding pushes Alaska and both
# Aleutian halves past the antimeridian (columns -1 and 257), which are
# not addressable tiles. Chart on the far side of 180 is covered by the
# OTHER Aleutian region, not by an out-of-range column here.
c0 = max(0, math.floor(col(WEST)))
c1 = min(256, math.ceil(col(EAST)))
bands = []
c = c0
while c < c1:
    d = min(c + COLS_PER_BAND, c1)
    bands.append(
        {"name": f"x{c:03d}-{d:03d}", "x0": c * Z8 - TILE0, "x1": d * Z8 - TILE0}
    )
    c = d
print(json.dumps(bands))
