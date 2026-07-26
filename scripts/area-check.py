"""Per-sheet cutline area vs a committed baseline.

Coverage sentinels catch a sheet losing a CITY; this catches a sheet
losing (or gaining) area anywhere. A detector that starts eating chart
shows up as a sheet shrinking well beyond printing-to-printing noise —
the frame detector once cut 3,673 boxes and deleted five states, and
every other gate passed.

Usage:
  python3 scripts/area-check.py <region>            # check, exit 1 on drift
  python3 scripts/area-check.py <region> --update   # rewrite the baseline
"""

import json
import os
import sys

sys.path.insert(0, "/repo/scripts")
from osgeo import ogr  # noqa: E402

import units  # noqa: E402

ogr.UseExceptions()

TOL = float(os.environ.get("AREA_TOL", "0.05"))  # 5%
BASELINE = "/repo/areas-baseline.json"


def area_of(path):
    if not os.path.exists(path):
        return 0.0
    g = ogr.CreateGeometryFromJson(
        json.dumps(json.load(open(path))["features"][0]["geometry"])
    )
    return float(g.GetArea()) if g else 0.0


def main(region, update):
    areas = {}
    for entry in units.read_list(region):
        _, _, cut = units.unit_paths(entry)
        side = cut.replace(".cutline.geojson", ".side.geojson")
        areas[entry] = round(area_of(cut) + area_of(side), 6)

    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    if update:
        base[region] = areas
        json.dump(base, open(BASELINE, "w"), indent=2, sort_keys=True)
        print(f"baseline updated for {region}: {len(areas)} sheets")
        return 0

    prev = base.get(region)
    if not prev:
        print(f"no baseline for {region}; run with --update to record one")
        return 0

    drift = []
    for entry, a in areas.items():
        p = prev.get(entry)
        if p is None:
            drift.append((entry, "new sheet, not in baseline"))
        elif p > 0 and abs(a - p) / p > TOL:
            drift.append((entry, f"{(a - p) / p:+.1%} ({p:.3f} -> {a:.3f} deg2)"))
    for entry in prev:
        if entry not in areas:
            drift.append((entry, "missing from this run"))

    if drift:
        print(f"AREA DRIFT ({region}): {len(drift)}/{len(areas)} sheets beyond {TOL:.0%}")
        for e, why in drift:
            print(f"   {e}: {why}")
        print("If intended (new cycle, deliberate change), rerun with --update.")
        return 1
    print(f"area OK ({region}): {len(areas)} sheets within {TOL:.0%} of baseline")
    return 0


if __name__ == "__main__":
    region = sys.argv[1] if len(sys.argv) > 1 else "conus"
    sys.exit(main(region, "--update" in sys.argv))
