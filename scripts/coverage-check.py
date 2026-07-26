"""Coverage sentinels: assert that well-known places still have chart.

The seam scanner hunts thin white strips and the hole gate ignores
chopped areas as intentional, so BOTH are blind to a detector that eats
real chart. A frame detector once produced 3,673 chops and deleted
Helena, Casper, Utah, Nevada and Flagstaff, and every automated check
still passed. This is the gate for that class: run it before any bake.

Usage: python3 scripts/coverage-check.py [region]
Exit 1 if any sentinel has no coverage.
"""

import math
import os
import sys

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

# Populated places spread across each region: if one of these loses its
# chart, something is very wrong.
SENTINELS = {
    "conus": {
        "Seattle": (-122.31, 47.45), "Portland": (-122.6, 45.59),
        "Missoula": (-114.09, 46.92), "Helena": (-111.98, 46.61),
        "Casper": (-106.46, 42.9), "Denver": (-104.67, 39.86),
        "Salt Lake City": (-111.98, 40.79), "Las Vegas": (-115.15, 36.08),
        "Reno": (-119.77, 39.5), "Flagstaff": (-111.67, 35.14),
        "Phoenix": (-112.01, 33.43), "Albuquerque": (-106.61, 35.04),
        "San Francisco": (-122.37, 37.62), "Los Angeles": (-118.41, 33.94),
        "Boise": (-116.22, 43.56), "Billings": (-108.54, 45.81),
        "Bismarck": (-100.75, 46.77), "Minneapolis": (-93.22, 44.88),
        "Omaha": (-95.89, 41.3), "Kansas City": (-94.71, 39.3),
        "Dallas": (-97.04, 32.9), "Houston": (-95.34, 29.98),
        "New Orleans": (-90.26, 29.99), "Miami": (-80.29, 25.79),
        "Orlando": (-81.31, 28.43), "Atlanta": (-84.43, 33.64),
        "Charlotte": (-80.94, 35.21), "Washington DC": (-77.46, 38.94),
        "New York": (-73.78, 40.64), "Boston": (-71.01, 42.36),
        "Bangor": (-68.83, 44.81), "Chicago": (-87.9, 41.98),
        "Detroit": (-83.35, 42.21), "Cleveland": (-81.85, 41.41),
        "St Louis": (-90.37, 38.75), "Memphis": (-89.98, 35.04),
    },
    "alaska": {
        "Anchorage": (-149.99, 61.17), "Fairbanks": (-147.86, 64.82),
        "Juneau": (-134.58, 58.36), "Nome": (-165.44, 64.51),
        "Kodiak": (-152.49, 57.75), "Barrow": (-156.77, 71.29),
        "Bethel": (-161.84, 60.78), "Ketchikan": (-131.71, 55.36),
    },
    "hawaii": {
        "Honolulu": (-157.92, 21.32), "Kahului": (-156.43, 20.9),
        "Kona": (-156.05, 19.74), "Lihue": (-159.34, 21.98),
    },
    "caribbean": {
        "San Juan": (-66.0, 18.44), "Aguadilla": (-67.13, 18.5),
        "St Thomas": (-64.97, 18.34), "St Croix": (-64.8, 17.7),
    },
    "mariana": {"Guam": (145.24, 13.48), "Saipan": (145.73, 15.12)},
    "samoa": {"Pago Pago": (-170.71, -14.33)},
    "aleutians_west": {"Shemya": (174.11, 52.71), "Attu": (172.95, 52.83)},
    "aleutians_far": {"Adak": (-176.65, 51.88), "Atka": (-174.2, 52.22)},
}


def main(region):
    path = f"/repo/data/{region}/preview/conus.vrt"
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
