#!/usr/bin/env python3
# Emit the tile-matrix shards as JSON: longitude bands aligned to z8
# tile columns in EPSG:3857, so band edges never split a tile and each
# shard's z8-12 pyramid is complete and disjoint.
import json
import math

TILE0 = 20037508.342789244
Z8 = 2 * TILE0 / 256  # z8 tile width in meters
WEST, EAST = -126.6, -60.6  # full lon range of the charts.txt set
COLS_PER_BAND = 6

def col(lon):
    return (lon + 180.0) / 360.0 * 256

c0 = math.floor(col(WEST))
c1 = math.ceil(col(EAST))
bands = []
c = c0
while c < c1:
    d = min(c + COLS_PER_BAND, c1)
    bands.append(
        {"name": f"x{c:03d}-{d:03d}", "x0": c * Z8 - TILE0, "x1": d * Z8 - TILE0}
    )
    c = d
print(json.dumps(bands))
