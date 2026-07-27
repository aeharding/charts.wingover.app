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


def region_extent(region):
    union = None
    for entry in units.read_list(region):
        _, _, cut = units.unit_paths(entry)
        for path in (cut, cut.replace(".cutline.", ".side.")):
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

    names = list(extents)
    bad = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            inter = extents[a].Intersection(extents[b])
            if inter and not inter.IsEmpty() and inter.GetArea() > TOL_DEG2:
                bad.append((a, b, inter.GetArea()))

    if bad:
        print(f"\nREGION OVERLAP: {len(bad)} pair(s) claim the same ground")
        for a, b, area in bad:
            print(f"   {a} x {b}: {area:.3f} deg2")
        print("Both regions tile into one keyspace; the later sync wins.")
        return 1
    print(f"\nregion overlap OK: {len(names)} regions, none share ground")
    return 0


if __name__ == "__main__":
    sys.exit(main())
