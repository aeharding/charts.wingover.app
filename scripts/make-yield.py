"""Regenerate yields/<region>.geojson: ground a region must NOT claim.

Two regions can chart the same ground. CONUS sectionals (1:500k) and the
Caribbean VFR (1:1M) both cover south Florida, 22.25 deg2 of it, and
every region ships into ONE vfr/<prefix>/3x/ keyspace. Without this the
winner is whichever tile job happens to sync last, which is both
non-deterministic and, at the boundary, lossy: a partially covered tile
can overwrite a fully covered one.

CONUS wins on overlap (Alex, 2026-07-27) because the sectional carries
twice the detail. So the Caribbean subtracts CONUS's coverage from its
own cutlines in finalize.py.

Why a committed polygon rather than computing it during the bake: each
region derives on its own runner and only ever holds its own cutlines,
so the Caribbean's job cannot see CONUS's geometry. A rectangle chop was
measured instead and rejected: it would wrongly delete 0.0062 deg2, a
~35 m sliver along lat 24 near the Keys, which is a visible hairline at
z12. finalize.py refuses to run against a stale file, keyed to the
outranking regions' chart lists (neatlines are printed on the sheet, so
they move when the sheet set changes, not every 56-day cycle).

Run where every region's cutlines exist on disk (the mac), after a full
derive:  python3 scripts/make-yield.py caribbean
"""

import hashlib
import json
import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

from osgeo import ogr  # noqa: E402

import units  # noqa: E402
import yields  # noqa: E402


ogr.UseExceptions()


def body_union(region):
    """Union of every body cutline in a region. Bodies only: overedge
    strips are underlay and reach across joins by design."""
    union = None
    missing = []
    for entry in units.read_list(region):
        _, _, cut = units.unit_paths(entry, region)
        if not os.path.exists(cut):
            missing.append(entry)
            continue
        g = ogr.CreateGeometryFromJson(
            json.dumps(json.load(open(cut))["features"][0]["geometry"])
        )
        if g and not g.IsEmpty():
            union = g.Clone() if union is None else union.Union(g)
    if missing:
        raise SystemExit(
            f"{region}: {len(missing)} cutlines missing on disk "
            f"(e.g. {missing[0]!r}); derive {region} first"
        )
    return union


def main(region):
    outranking = yields.outranked_by(region)
    if not outranking:
        raise SystemExit(f"{region} declares no yields_to in regions.json")

    union = None
    for other in outranking:
        g = body_union(other)
        union = g if union is None else union.Union(g)
    union.Segmentize(0.05)

    os.makedirs(f"{REPO}/yields", exist_ok=True)
    path = f"{REPO}/yields/{region}.geojson"
    json.dump(
        {
            "type": "FeatureCollection",
            "yields_to": outranking,
            "lists_sha": yields.lists_sha(outranking),
            "features": [
                {
                    "type": "Feature",
                    "properties": {"note": f"coverage of {', '.join(outranking)}"},
                    "geometry": json.loads(union.ExportToJson()),
                }
            ],
        },
        open(path, "w"),
    )
    print(f"wrote {path}: {union.GetArea():.2f} deg2 from {outranking}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
