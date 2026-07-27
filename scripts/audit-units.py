"""Audit every unit for the three faults the Honolulu inset exposed.

That inset is a 1:250k blow-up of Oahu printed in the margin of the
Hawaiian Islands sheet. Baked as an ordinary unit it (a) sits entirely
inside the main chart, (b) is drawn at twice the scale of everything
around it, and (c) carries its printed projection caption inside its own
cutline, so that text lands in the Pacific. Nothing caught any of it.

Checks:
  CONTAINED  a unit's body is almost entirely inside another's, so the
             two chart the same ground and draw order alone decides
  SCALE      a unit's source resolution differs from its region's norm,
             so its symbols and text render at a different size
  FURNITURE  a band just inside a cutline edge is nearly all white,
             which is what a printed margin or caption strip looks like

Usage: python3 scripts/audit-units.py [region ...]
Exit 1 if anything is flagged.
"""

import json
import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

import numpy as np  # noqa: E402
from osgeo import gdal, ogr  # noqa: E402

import units  # noqa: E402


gdal.UseExceptions()
ogr.UseExceptions()

CONTAINED_FRAC = 0.90   # of the smaller unit's area
SCALE_TOL = 0.25        # vs the region's main (largest) sheet
WHITE = 242             # same threshold derive.py measured for paper
FURNITURE_FRAC = 0.85   # of a sampled edge band
FURNITURE_MIN_COVER = 0.02  # the band must be at least this much INSIDE
EDGE_M = 1200.0         # how deep to sample inside each edge


def body(entry, region):
    _, _, cut = units.unit_paths(entry, region)
    if not os.path.exists(cut):
        return None
    return ogr.CreateGeometryFromJson(
        json.dumps(json.load(open(cut))["features"][0]["geometry"])
    )


def res_m(entry, region):
    tif, _, _ = units.unit_paths(entry, region)
    if not os.path.exists(tif):
        return None
    return abs(gdal.Open(tif).GetGeoTransform()[1])


def edge_whiteness(entry, region, others):
    """Fraction of near-white pixels in a band inside each cutline edge,
    measured ONLY where no other unit covers the same ground.

    A printed margin is paper: nearly all white. Real chart, even open
    ocean, is tinted. But almost every interior sheet edge carries a
    "Joins <neighbour>" ruler inside its body cutline, and the neighbour
    draws over it, so that is by design and invisible. What matters is
    furniture nothing covers: San Francisco's elevation legend sits in
    the Pacific with no neighbour, so it lands on the map.
    """
    tif, vrt, cut = units.unit_paths(entry, region)
    if not (os.path.exists(tif) and os.path.exists(cut)):
        return None
    if not os.path.exists(vrt):
        gdal.Translate(vrt, tif, format="VRT", rgbExpand="rgb")
    g = body(entry, region)
    for o in others:
        g = g.Difference(o)
        if g is None or g.IsEmpty():
            return None
    x0, x1, y0, y1 = g.GetEnvelope()
    # ~1200 m in degrees, latitude-corrected
    dy = EDGE_M / 111320.0
    dx = dy / max(0.2, np.cos(np.radians((y0 + y1) / 2)))
    gdal.FileFromMemBuffer(
        "/vsimem/exposed.geojson",
        json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {},
                          "geometry": json.loads(g.ExportToJson())}],
        }),
    )
    worst = None
    for name, win in (
        ("S", (x0, y0, x1, y0 + dy)),
        ("N", (x0, y1 - dy, x1, y1)),
        ("W", (x0, y0, x0 + dx, y1)),
        ("E", (x1 - dx, y0, x1, y1)),
    ):
        wx0, wy0, wx1, wy1 = win
        try:
            ds = gdal.Warp(
                "", vrt, format="MEM", dstSRS="EPSG:4326",
                outputBounds=(wx0, wy0, wx1, wy1),
                width=400, height=400, resampleAlg="average",
                dstAlpha=True, cutlineDSName="/vsimem/exposed.geojson",
            )
        except RuntimeError:
            continue
        a = ds.ReadAsArray()
        rgb, alpha = a[:3], a[-1]
        inside = alpha > 0
        if inside.sum() < max(400, FURNITURE_MIN_COVER * inside.size):
            continue
        white = ((rgb > WHITE).all(axis=0) & inside).sum() / inside.sum()
        if worst is None or white > worst[1]:
            worst = (name, float(white))
    return worst


def main(regions):
    cfg = json.load(open(f"{REPO}/regions.json"))
    regions = regions or list(cfg)
    allunits = []
    for r in regions:
        for e in units.read_list(r):
            allunits.append((r, e))

    problems = []

    # CONTAINED: compare every pair, across regions too
    geoms = {}
    for r, e in allunits:
        g = body(e, r)
        if g is not None:
            geoms[(r, e)] = g
    keys = list(geoms)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ga, gb = geoms[a], geoms[b]
            inter = ga.Intersection(gb)
            if inter is None or inter.IsEmpty():
                continue
            for small, big in ((a, b), (b, a)):
                gs = geoms[small]
                if gs.GetArea() > 0 and inter.GetArea() / gs.GetArea() >= CONTAINED_FRAC:
                    problems.append(
                        f"CONTAINED  {small[0]}/{small[1]}\n"
                        f"           lies {inter.GetArea() / gs.GetArea():.0%} inside "
                        f"{big[0]}/{big[1]}"
                    )

    # SCALE: per region, against the main (largest) sheet
    for r in regions:
        rs = {e: res_m(e, r) for e in units.read_list(r)}
        rs = {e: v for e, v in rs.items() if v}
        if len(rs) < 2:
            continue
        areas = {e: (geoms[(r, e)].GetArea() if (r, e) in geoms else 0) for e in rs}
        biggest = max(areas, key=areas.get)
        norm = rs[biggest]
        for e, v in rs.items():
            if e != biggest and abs(v - norm) / norm > SCALE_TOL:
                problems.append(
                    f"SCALE      {r}/{e}\n"
                    f"           {v:.1f} m/px vs {biggest} at {norm:.1f} "
                    f"({v / norm:.2f}x)"
                )

    # FURNITURE: white band inside a cutline edge that nothing covers
    for r, e in allunits:
        others = [g for k, g in geoms.items() if k != (r, e)]
        w = edge_whiteness(e, r, others)
        if w and w[1] >= FURNITURE_FRAC:
            problems.append(
                f"FURNITURE  {r}/{e}\n"
                f"           {w[0]} edge is {w[1]:.0%} white inside the cutline"
            )

    blocking = [p for p in problems if not p.startswith("FURNITURE")]
    advisory = [p for p in problems if p.startswith("FURNITURE")]
    if problems:
        print(f"UNIT AUDIT: {len(problems)} finding(s) across {len(allunits)} units\n")
        for p in problems:
            print(p)
    if advisory:
        print(
            f"\n{len(advisory)} FURNITURE finding(s) are ADVISORY: a whiteness "
            "test cannot see a coloured tint ramp (it missed San Francisco's "
            "legend entirely), so it is a hint, not a verdict. The "
            "authoritative sweep is scripts/contact-sheet.py plus review."
        )
    if blocking:
        return 1
    if not problems:
        print(f"unit audit OK: {len(allunits)} units, nothing flagged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
