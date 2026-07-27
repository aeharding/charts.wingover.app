#!/usr/bin/env python3
"""Emit the tile-matrix shards as JSON.

Longitude bands aligned to z8 tile columns in EPSG:3857, so a band edge
never splits a tile and each shard's z8-12 pyramid is complete.

Pass a region name for that region's bands, or "all" for ONE global band
set covering every region. Global is what the bake uses: tile keys are
z/x/y with no region in the path, so two regions charting the same ground
(CONUS sectionals and the Caribbean VFR both cover south Florida) would
otherwise be tiled by two jobs writing the same keys, and whichever
synced last would win. Worse, a tile the boundary crosses would be half
blank whichever way the race went. One global band set means each tile is
built once, from every sheet that touches it.
"""

import json
import math
import os
import sys

# Repo root resolved from THIS FILE, never hardcoded: the CI plan job
# runs outside the container where /repo does not exist. bands.py
# failing there produced an EMPTY tile matrix, so every tile job
# skipped silently and the bake shipped only z0-7.
REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

TILE0 = 20037508.342789244
Z8 = 2 * TILE0 / 256  # z8 tile width in meters
COLS_PER_BAND = 3


def col(lon):
    return (lon + 180.0) / 360.0 * 256


def columns(grid):
    """z8 columns a region's grid covers, clamped to the addressable grid.

    The half-degree pad pushes Alaska and both Aleutian halves past the
    antimeridian (columns -1 and 257), which are not tiles. Chart on the
    far side of 180 belongs to the OTHER Aleutian region.
    """
    west, east = grid[0] - 0.5, grid[2] + 0.5
    return range(max(0, math.floor(col(west))), min(256, math.ceil(col(east))))


def main(region):
    cfg = json.load(open(f"{REPO}/regions.json"))
    if region == "all":
        # UNION of the regions' columns, not min..max: the regions span
        # the Aleutians to the Caribbean, so a plain span would emit ~37
        # bands of empty ocean, each paying a full job to find nothing.
        cols = sorted({c for r in cfg.values() for c in columns(r["grid"])})
    else:
        cols = sorted(columns(cfg[region]["grid"]))

    bands = []
    for c in cols:
        # start a new band at a gap, or when the current one is full
        if (
            not bands
            or c != bands[-1][-1] + 1
            or len(bands[-1]) >= COLS_PER_BAND
        ):
            bands.append([c])
        else:
            bands[-1].append(c)

    return [
        {
            "name": f"x{b[0]:03d}-{b[-1] + 1:03d}",
            "x0": b[0] * Z8 - TILE0,
            "x1": (b[-1] + 1) * Z8 - TILE0,
        }
        for b in bands
    ]


if __name__ == "__main__":
    region = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REGION", "conus")
    print(json.dumps(main(region)))
