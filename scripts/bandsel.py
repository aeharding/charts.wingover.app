"""Select the sheets in a tile band and derive the band's Y extent.

Shared by the CI tile job and the local tile dry run so the two cannot
drift. The Y extent used to be hardcoded in the workflow to
2600000..6500000, which is exactly CONUS's 22.7N..50.3N: every other
region was clipped to nothing and tiled to zero tiles, and nothing
caught it until a band was made to fail on an empty output.

Usage:
  python3 scripts/bandsel.py <region> <x0> <x1> <uri-template>

uri-template takes {uid}, so the same code serves object storage
(/vsis3/bucket/scratch/<run>/warped/{uid}.tif) and local disk
(warped/{uid}.tif). Writes fetch.txt (one uid per line) and bandy.env
(BY0/BY1) into the current directory.
"""

import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

from osgeo import gdal  # noqa: E402

import units  # noqa: E402


gdal.UseExceptions()


def main(region, x0, x1, template):
    sel, ys = [], []
    for entry in units.read_list(region):
        # UNIT IDS, not raw entries: warp writes "$UNIT.tif" with spaces
        # and :: sanitised, so paths built from chart lines 404 for every
        # multi-scan sheet (Hawaii, Marianas, Samoa, both Aleutians).
        uid = units.unit_id(entry)
        cc = gdal.Info(template.format(uid=uid), format="json")["cornerCoordinates"]
        if cc["lowerRight"][0] > x0 and cc["upperLeft"][0] < x1:
            sel.append(uid)
            ys += [cc["lowerRight"][1], cc["upperLeft"][1]]
    if not sel:
        raise SystemExit(f"no sheets intersect band {x0}..{x1} of {region}")
    with open("fetch.txt", "w") as f:
        f.write("\n".join(sel) + "\n")
    with open("bandy.env", "w") as f:
        f.write(f"BY0={min(ys)}\nBY1={max(ys)}\n")
    return sel, min(ys), max(ys)


if __name__ == "__main__":
    region, x0, x1, template = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    sel, y0, y1 = main(region, x0, x1, template)
    print(f"{len(sel)} sheets, Y {y0:.0f}..{y1:.0f}", file=sys.stderr)
