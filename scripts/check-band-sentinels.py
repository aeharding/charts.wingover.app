"""Assert a band produced the sentinel tiles that fall inside it.

The gates before this check the PREVIEW mosaic; verify checks PUBLISHED
objects and so cannot run on a dry run. Between them sat the one thing
neither could see: whether the band a city sits in actually emitted that
city's tile. A bake has twice reported success while shipping almost
nothing, so this closes the gap on both sides - a dry run now proves
coverage without publishing, and a real bake fails BEFORE syncing rather
than after.

Usage: python3 scripts/check-band-sentinels.py <x0> <x1> <tiles-dir>
"""

import math
import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

from sentinels import SENTINELS  # noqa: E402

TILE0 = 20037508.342789244
Z = 12


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def main(x0, x1, tiles):
    checked, missing = 0, []
    for region, cities in SENTINELS.items():
        for name, (lon, lat) in cities.items():
            merc_x = lon * TILE0 / 180.0
            # A tile belongs to exactly one band, so only test the
            # sentinels this band is actually responsible for.
            if not (x0 <= merc_x < x1):
                continue
            checked += 1
            x, y = tile_xy(lon, lat, Z)
            if not os.path.exists(f"{tiles}/{Z}/{x}/{y}.jxl"):
                missing.append(f"{region}/{name} -> {Z}/{x}/{y}")
    if missing:
        print(f"BAND LOST {len(missing)} of {checked} SENTINELS:", file=sys.stderr)
        for m in missing:
            print(f"   {m}", file=sys.stderr)
        return 1
    print(f"band sentinels OK: {checked} in this band, all present")
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]))
