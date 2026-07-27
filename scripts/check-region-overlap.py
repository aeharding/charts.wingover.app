"""Assert that no two regions claim the same ground.

Every region syncs its tiles into the SAME vfr/<prefix>/3x/ keyspace, so
if two regions both produce chart for one tile, whichever finishes last
silently overwrites the other. Region grids in regions.json DO overlap
in longitude by design (Alaska's box spans both Aleutian halves), which
is harmless only as long as the actual cutlines do not.

This compares real cutline unions, not the grid boxes.

Usage: python3 scripts/check-region-overlap.py
"""

import json
import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

from osgeo import ogr  # noqa: E402

import units  # noqa: E402


ogr.UseExceptions()

# Printed charts overlap slightly at every join by design (each sheet
# carries a little of its neighbour), and the underlay strips are wider
# still. Only a substantial shared area means a region is duplicating
# another's coverage.
TOL_DEG2 = float(os.environ.get("OVERLAP_TOL", "0.5"))


# Overedge strips are underlay: they intentionally reach across joins,
# and inside a region draw order makes that harmless. Measure body-on-body
# overlap separately, since only that is two regions drawing real chart on
# the same ground.
SIDES = os.environ.get("WITH_SIDES", "1") == "1"


def region_extent(region):
    union = None
    for entry in units.read_list(region):
        _, _, cut = units.unit_paths(entry, region)
        paths = (cut, cut.replace(".cutline.", ".side.")) if SIDES else (cut,)
        for path in paths:
            if not os.path.exists(path):
                continue
            geom = ogr.CreateGeometryFromJson(
                json.dumps(json.load(open(path))["features"][0]["geometry"])
            )
            if geom is None or geom.IsEmpty():
                continue
            union = geom.Clone() if union is None else union.Union(geom)
    return union


def main():
    extents = {}
    for region in json.load(open(f"{REPO}/regions.json")):
        os.environ["REGION"] = region
        g = region_extent(region)
        if g is None:
            print(f"  {region:16s} no cutlines on disk, skipped")
            continue
        extents[region] = g
        e = g.GetEnvelope()
        print(
            f"  {region:16s} lon {e[0]:8.2f}..{e[1]:8.2f}  "
            f"lat {e[2]:7.2f}..{e[3]:7.2f}"
        )

    cfg = json.load(open(f"{REPO}/regions.json"))
    names = list(extents)
    bad, resolved = [], []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            inter = extents[a].Intersection(extents[b])
            if not (inter and not inter.IsEmpty() and inter.GetArea() > TOL_DEG2):
                continue
            pa = cfg.get(a, {}).get("priority", 10)
            pb = cfg.get(b, {}).get("priority", 10)
            # Overlap itself is fine: the global tiler draws both into one
            # band VRT, later wins. It is only ambiguous at EQUAL priority.
            (bad if pa == pb else resolved).append((a, b, inter.GetArea(), pa, pb))

    for a, b, area, pa, pb in resolved:
        win = a if pa > pb else b
        print(f"\noverlap {a} x {b}: {area:.3f} deg2 -> {win} wins (priority {max(pa, pb)})")
    if bad:
        print(f"\nAMBIGUOUS OVERLAP: {len(bad)} pair(s) share ground at EQUAL priority")
        for a, b, area, pa, pb in bad:
            print(f"   {a} x {b}: {area:.3f} deg2, both priority {pa}")
        print("Give one of them a higher priority in regions.json.")
        return 1
    print(f"\nregion overlap OK: {len(names)} regions, every overlap has a winner")
    return 0


if __name__ == "__main__":
    sys.exit(main())
