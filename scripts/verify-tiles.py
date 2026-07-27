"""Verify a region actually shipped tiles, in its OWN part of the grid.

The previous check counted every object under vfr/<prefix>/3x/, which
all 8 regions share. Samoa's floor of 100 was therefore satisfied by
CONUS's 240,000 tiles, so a region that shipped NOTHING still passed.
Two bakes have already reported success while shipping almost nothing;
this is the gate that has to stop the third.

Checks, per region:
  1. z8 tiles exist inside the region's own band columns (cheap listing,
     bounded by the region's width, and blind to other regions).
  2. every coverage sentinel city has a real z12 tile, via head-object.

Usage: python3 scripts/verify-tiles.py <region> <prefix>
Env: BUCKET, AWS_* , R2_ENDPOINT
"""

import json
import math
import os
import subprocess
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

BUCKET = os.environ["BUCKET"]
ENDPOINT = os.environ["R2_ENDPOINT"]

# Reuse the sentinel cities the coverage gate already uses, so the two
# gates cannot disagree about what "has chart" means.
from sentinels import SENTINELS  # noqa: E402

# A region ships at least this many z8 tiles. Small regions are a couple
# of islands; CONUS is a continent.
FLOORS = {
    "conus": 400, "alaska": 120, "caribbean": 25, "hawaii": 8,
    "aleutians_west": 4, "aleutians_far": 4, "mariana": 3, "samoa": 2,
}


def aws(*args):
    return subprocess.run(
        ["aws", "--endpoint-url", ENDPOINT, *args],
        capture_output=True, text=True,
    )


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int(
        (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    )
    return x, y


def main(region, prefix):
    bands = json.loads(
        subprocess.check_output(["python3", f"{REPO}/scripts/bands.py", region])
    )
    cols = set()
    for b in bands:
        lo, hi = (int(p) for p in b["name"][1:].split("-"))
        cols.update(range(lo, hi))

    # 1. z8 tiles in this region's columns only
    n8 = 0
    for c in sorted(cols):
        r = aws("s3", "ls", "--recursive", f"s3://{BUCKET}/{prefix}/3x/8/{c}/")
        n8 += sum(1 for line in r.stdout.splitlines() if line.strip())
    floor = FLOORS.get(region, 2)
    print(f"{region}: {n8} z8 tiles across {len(cols)} columns (floor {floor})")
    if n8 < floor:
        print(f"REGION SHIPPED TOO LITTLE: {region} has {n8} z8 tiles", file=sys.stderr)
        return 1

    # 2. every sentinel city has a real z12 tile
    missing = []
    for name, (lon, lat) in SENTINELS.get(region, {}).items():
        x, y = tile_xy(lon, lat, 12)
        key = f"{prefix}/3x/12/{x}/{y}.jxl"
        if aws("s3api", "head-object", "--bucket", BUCKET, "--key", key).returncode:
            missing.append(f"{name} ({key})")
    if missing:
        print(f"MISSING SENTINEL TILES ({region}):", file=sys.stderr)
        for m in missing:
            print(f"   {m}", file=sys.stderr)
        return 1
    print(f"{region}: {len(SENTINELS.get(region, {}))}/{len(SENTINELS.get(region, {}))} sentinel tiles present")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2].rstrip("/")))
