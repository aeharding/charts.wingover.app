"""Pick the sheets in a tile band and put them in DRAW ORDER.

Shared by the CI tile job and the local tile dry run so the two cannot
drift. Writes, into the current directory:

  fetch.txt   one "<region>\\t<uid>\\t<suffix>" per line, in draw order
  bandy.env   BY0/BY1, the band's Y extent

Two things this file decides.

DRAW ORDER. Later wins in a VRT, so the order is: every OVEREDGE strip
first, then every BODY, each group by region priority ascending. Overedge
is underlay: a sheet's printed neatline stroke sits on it, and wherever a
neighbour has clean map over the same ground the neighbour's body covers
that stroke. Leaving it to alphabetical order is what left a black line
across 44N by Matinicus. Priority then settles who wins where two regions
chart the same ground: CONUS sectionals (1:500k) beat the Caribbean VFR
(1:1M) over south Florida.

GLOBAL SELECTION. Pass "all" and every region is considered together.
Tile keys carry no region, so per-region tiling had two jobs writing the
same keys where regions overlap, and a tile the boundary crossed came out
half blank whichever job synced last.

Usage:
  python3 scripts/bandsel.py <region|all> <x0> <x1> <uri-template>

The template takes {region}, {uid} and {suffix} ("" or ".side"), so the
same code serves object storage and local disk.
"""

import json
import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

from osgeo import gdal  # noqa: E402

import units  # noqa: E402


gdal.UseExceptions()

# Select a little wider than the band. A unit whose BODY sits just
# outside can still have an overedge strip reaching in, and dropping it
# would leave a hairline at the band edge. One z8 column is ~156 km; half
# of that is far more than any overedge and costs only a spare download.
MARGIN = 20037508.342789244 / 256


def regions_for(region):
    cfg = json.load(open(f"{REPO}/regions.json"))
    names = list(cfg) if region == "all" else [region]
    # ascending priority: the LAST one drawn wins
    return sorted(names, key=lambda r: (cfg[r].get("priority", 10), r))


ALLOW_MISSING = os.environ.get("BANDSEL_ALLOW_MISSING") == "1"


def main(region, x0, x1, template):
    sel, ys, skipped = [], [], []
    for r in regions_for(region):
        for entry in units.read_list(r):
            # UNIT IDS, not raw entries: warp writes "$UNIT.tif" with
            # spaces and :: sanitised, so paths built from chart lines
            # 404 for every multi-scan sheet.
            uid = units.unit_id(entry)
            uri = template.format(region=r, uid=uid, suffix="")
            try:
                cc = gdal.Info(uri, format="json")["cornerCoordinates"]
            except RuntimeError:
                # STRICT by default. In the bake every unit is warped
                # before tiling (tile needs prepare), so a missing one
                # means a sheet would silently vanish from the product -
                # exactly the failure that shipped a bake of 56 tiles and
                # called it success. Only the local dry run, which
                # prepares a subset on purpose, opts out.
                if not ALLOW_MISSING:
                    raise
                skipped.append(f"{r}/{uid}")
                continue
            if (
                cc["lowerRight"][0] > x0 - MARGIN
                and cc["upperLeft"][0] < x1 + MARGIN
            ):
                sel.append((r, uid))
                ys += [cc["lowerRight"][1], cc["upperLeft"][1]]
    if skipped:
        print(f"SKIPPED {len(skipped)} unwarped units: {skipped[:4]}", file=sys.stderr)
    if not sel:
        raise SystemExit(f"no sheets intersect band {x0}..{x1}")

    with open("fetch.txt", "w") as f:
        # sides (underlay) first, then bodies; each already in priority order
        for suffix in (".side", ""):
            for r, uid in sel:
                f.write(f"{r}\t{uid}\t{suffix}\n")
    with open("bandy.env", "w") as f:
        # The band's Y extent is the union of ITS OWN sheets. It used to
        # be hardcoded to 2600000..6500000, which is exactly CONUS's
        # 22.7N..50.3N: every other region was clipped to nothing.
        f.write(f"BY0={min(ys)}\nBY1={max(ys)}\n")
    return sel, min(ys), max(ys)


if __name__ == "__main__":
    region, x0, x1, template = (
        sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4],
    )
    sel, y0, y1 = main(region, x0, x1, template)
    print(f"{len(sel)} sheets, Y {y0:.0f}..{y1:.0f}", file=sys.stderr)
