"""Coverage sentinels: assert that well-known places still have chart.

The seam scanner hunts thin white strips and the hole gate ignores
chopped areas as intentional, so BOTH are blind to a detector that eats
real chart. A frame detector once produced 3,673 chops and deleted
Helena, Casper, Utah, Nevada and Flagstaff, and every automated check
still passed. This is the gate for that class: run it before any bake.

Usage: python3 scripts/coverage-check.py [region]
Exit 1 if any sentinel has no coverage.
"""

import os

# Repo root resolved from THIS FILE, never hardcoded: the CI plan job
# runs outside the container where /repo does not exist. bands.py
# failing there produced an EMPTY tile matrix, so every tile job
# skipped silently and the bake shipped only z0-7.
REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


import math
import os
import sys

import numpy as np
from osgeo import gdal


gdal.UseExceptions()

# Populated places spread across each region: if one of these loses its
# chart, something is very wrong.
from sentinels import SENTINELS  # noqa: E402



def main(region):
    path = f"{REPO}/data/{region}/preview/conus.vrt"
    if not os.path.exists(path):
        print(f"no preview for {region}; render it first")
        return 1
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    bad = []
    for name, (lon, lat) in SENTINELS.get(region, {}).items():
        X = lon * 20037508.342789244 / 180
        Y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137
        x = int((X - gt[0]) / gt[1])
        y = int((gt[3] - Y) / gt[1])
        if not (0 <= x < ds.RasterXSize and 0 <= y < ds.RasterYSize):
            bad.append((name, "outside mosaic"))
            continue
        a = ds.ReadAsArray(max(x - 8, 0), max(y - 8, 0), 16, 16)
        cov = float((a[3] > 0).mean())
        if cov < 0.5:
            bad.append((name, f"coverage {cov:.2f}"))
    total = len(SENTINELS.get(region, {}))
    if bad:
        print(f"COVERAGE FAILURE ({region}): {len(bad)}/{total} sentinels lost chart")
        for n, why in bad:
            print(f"   {n}: {why}")
        return 1
    print(f"coverage OK ({region}): {total}/{total} sentinels have chart")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "conus"))
