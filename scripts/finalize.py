# Finalize cutlines: arbitrate YIELD side columns, subtract detected
# inset boxes, hole-gate the union coverage, and emit densified
# MultiPolygon cutlines per sheet.
#
# derive.py ships per sheet: polys (pixel-snapped map body, side columns
# excluded), side (the outermost 3 columns per true side edge, snapped),
# and insets (auto-detected addendum boxes to chop). Side columns carry
# the LCC-tilted white margin, so they are kept ONLY where no other
# sheet's body covers them: dropped at interior joints (deep overlap,
# neighbor is pure map), kept at true rims (Matinicus Isle lives in New
# York's east side columns with nothing else covering it).
import json
import os
import sys

import numpy as np
from osgeo import ogr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import units  # noqa: E402

ogr.UseExceptions()

CELL = 1 / 12
REGION = os.environ.get("REGION", "conus")
DATA = f"/repo/data/{REGION}/dataregions.json"
regions = json.load(open(DATA))

# hole-gate grid for this region (regions.json)
W0, S0, E0, N0 = json.load(open("/repo/regions.json"))[REGION]["grid"]
GW = round((E0 - W0) / CELL)
GH = round((N0 - S0) / CELL)

# Union grid of body coverage with HALF-CELL tolerance: pixel-snapped
# body edges sit mid-cell, and demanding full containment made every
# neighbor edge cell read "uncovered" — yield columns were then kept at
# interior joints and painted their white-margin fraction over the
# neighbor as thin vertical slivers.
body_grid = np.zeros((GH, GW), bool)
for chart, r in regions.items():
    for poly in r["polys"]:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        gc0 = int(np.ceil((min(xs) - W0) / CELL - 0.5))
        gc1 = int(np.floor((max(xs) - W0) / CELL + 0.5))
        gr0 = int(np.ceil((min(ys) - S0) / CELL - 0.5))
        gr1 = int(np.floor((max(ys) - S0) / CELL + 0.5))
        body_grid[max(gr0, 0) : min(gr1, GH), max(gc0, 0) : min(gc1, GW)] = True

def ring(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]

def to_ogr(rings):
    """List of closed rings -> OGR MultiPolygon (unioned)."""
    mp = ogr.Geometry(ogr.wkbMultiPolygon)
    for r in rings:
        poly = ogr.Geometry(ogr.wkbPolygon)
        lr = ogr.Geometry(ogr.wkbLinearRing)
        for x, y in r:
            lr.AddPoint_2D(float(x), float(y))
        poly.AddGeometry(lr)
        mp.AddGeometry(poly)
    return mp.UnionCascaded() if mp.GetGeometryCount() > 1 else mp

def rings_of(geom):
    """OGR geometry -> list of exterior rings (holes are emitted as
    separate cutline features by the caller; gdalwarp honours them)."""
    out = []
    if geom is None or geom.IsEmpty():
        return out
    t = geom.GetGeometryName()
    if t == "POLYGON":
        for i in range(geom.GetGeometryCount()):
            r = geom.GetGeometryRef(i)
            out.append([(r.GetX(j), r.GetY(j)) for j in range(r.GetPointCount())])
    elif t in ("MULTIPOLYGON", "GEOMETRYCOLLECTION"):
        for i in range(geom.GetGeometryCount()):
            out.extend(rings_of(geom.GetGeometryRef(i)))
    return out

final = {}
prechop = {}
kept_sides = dropped_sides = 0
for chart, r in regions.items():
    polys = list(r["polys"])
    for poly in r["side"]:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        gc0 = int(np.ceil((min(xs) - W0) / CELL - 0.5))
        gc1 = int(np.floor((max(xs) - W0) / CELL + 0.5))
        gr0 = int(np.ceil((min(ys) - S0) / CELL - 0.5))
        gr1 = int(np.floor((max(ys) - S0) / CELL + 0.5))
        gr0, gr1 = max(gr0, 0), min(gr1, GH)
        # Keep the side wherever the neighbor's body does NOT cover it:
        # dropped at deep-overlap joints (neighbor's pure map wins),
        # kept at abutting pairs and true rims (Matinicus).
        covered = body_grid[gr0:gr1, max(gc0, 0) : min(gc1, GW)].all()
        if covered:
            dropped_sides += 1
        else:
            kept_sides += 1
            polys.append(poly)
    # Addendum chops are TILTED quads (rectangles in the sheet's own
    # projection), so subtraction needs real polygon booleans — GEOS via
    # OGR — not the axis-aligned rect splitting this used to do.
    prechop[chart] = list(polys)
    # ALWAYS union: a cutline of hundreds of overlapping parts made
    # gdalwarp re-clip per block and blew the render from 5 to 80
    # minutes. One clean geometry per sheet.
    geom = to_ogr([[(p[0], p[1]) for p in poly] for poly in polys])
    for quad in r["insets"]:
        geom = geom.Difference(to_ogr([[(p[0], p[1]) for p in quad]]))
    geom.Segmentize(0.05)
    final[chart] = geom
print(f"side columns: {kept_sides} kept (rims), {dropped_sides} dropped (covered joints)")

# CONDITIONAL EDGE RETREAT (rectangle arithmetic, never GEOS).
# Sheet edges must pull back ~550 m inside their printed ink so a
# neatline stroke cannot paint over a neighbour — but only where a
# neighbour is actually there. Where sheets merely ABUT (New York and
# Halifax at 44N by Matinicus; Cheyenne and Omaha at 101W) pulling both
# back leaves an empty hairline on the graticule. Buffer-based fills
# were tried first and kept producing geometry that would not survive
# being written; deciding per slab keeps everything rectangular and
# valid by construction.
RETREAT = 0.005  # degrees (~550 m)

# Exact point-in-coverage per sheet (slab rectangles, vectorised).
# A CELL-granular test is useless here: cells are 5 minutes (~9 km) and
# the retreat is 550 m, so when two sheets' edges COINCIDE at 44N the
# cell test says "neighbour covers" for both, both retreat, and the
# hairline survives. The rule must be: retreat only where a neighbour
# reaches PAST my edge.
rects = {}
for chart, polys in prechop.items():
    if not polys:
        rects[chart] = None
        continue
    arr = np.array(
        [
            [
                min(p[0] for p in poly),
                max(p[0] for p in poly),
                min(p[1] for p in poly),
                max(p[1] for p in poly),
            ]
            for poly in polys
        ]
    )
    rects[chart] = arr


def covered_by_self(chart, lon, lat, skip):
    """Does this sheet itself continue past the edge? Slab boundaries
    between a sheet's own adjacent bands are NOT real edges — retreating
    at them made the sheet pull away from itself, which is what actually
    opened the 44N hairline (New York's own band seam), not the joint
    with Halifax."""
    arr = rects.get(chart)
    if arr is None:
        return False
    hit = (
        (arr[:, 0] <= lon)
        & (lon <= arr[:, 1])
        & (arr[:, 2] <= lat)
        & (lat <= arr[:, 3])
    )
    hit[skip] = False
    return bool(np.any(hit))


def covered_by_others(chart, lon, lat):
    for o, arr in rects.items():
        if o == chart or arr is None:
            continue
        if np.any(
            (arr[:, 0] <= lon)
            & (lon <= arr[:, 1])
            & (arr[:, 2] <= lat)
            & (lat <= arr[:, 3])
        ):
            return True
    return False


retreated = abutting = internal = 0
tentative = {}
for chart, polys in prechop.items():
    out = []
    for idx, poly in enumerate(polys):
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        xm = (x0 + x1) / 2
        ry1, ry0 = y1, y0
        if covered_by_self(chart, xm, y1 + RETREAT * 0.5, idx):
            internal += 1
        elif covered_by_others(chart, xm, y1 + RETREAT * 2.5):
            ry1 = y1 - RETREAT
            retreated += 1
        else:
            abutting += 1
        if covered_by_self(chart, xm, y0 - RETREAT * 0.5, idx):
            internal += 1
        elif covered_by_others(chart, xm, y0 - RETREAT * 2.5):
            ry0 = y0 + RETREAT
            retreated += 1
        else:
            abutting += 1
        out.append([x0, x1, y0, y1, ry0, ry1])
    tentative[chart] = out

# VERIFY, THEN UNDO. Probing that a neighbour covers my edge is not
# enough: it may retreat from that very strip itself. At 44N by
# Matinicus the sheets overlapped by 0.0002 deg, both retreated 0.005,
# and the strip both had relied on vanished. Re-check every retreat
# against POST-retreat coverage and put back the ones that would leave
# a hole.
post = {}
for chart, rows in tentative.items():
    post[chart] = np.array([[r[0], r[1], r[4], r[5]] for r in rows]) if rows else None


def post_covered(chart, lon, lat):
    for o, arr in post.items():
        if o == chart or arr is None:
            continue
        if np.any(
            (arr[:, 0] <= lon) & (lon <= arr[:, 1]) & (arr[:, 2] <= lat) & (lat <= arr[:, 3])
        ):
            return True
    return False


undone = 0
for chart, rows in tentative.items():
    for r in rows:
        x0, x1, y0, y1, ry0, ry1 = r
        xm = (x0 + x1) / 2
        if ry1 < y1 and not post_covered(chart, xm, (ry1 + y1) / 2):
            r[5] = y1
            undone += 1
        if ry0 > y0 and not post_covered(chart, xm, (ry0 + y0) / 2):
            r[4] = y0
            undone += 1

for chart, rows in tentative.items():
    out = []
    for x0, x1, y0, y1, ry0, ry1 in rows:
        if ry1 > ry0:
            out.append([[x0, ry0], [x1, ry0], [x1, ry1], [x0, ry1], [x0, ry0]])
    prechop[chart] = out
print(
    f"edges: {retreated} retreated, {abutting} kept (abutting/rim), "
    f"{internal} own-band seams, {undone} retreats undone (would have holed)"
)

# rebuild the shipped geometry from the adjusted slabs
for chart in list(final):
    geom = to_ogr([[(p[0], p[1]) for p in poly] for poly in prechop[chart]])
    for quad in regions[chart]["insets"]:
        geom = geom.Difference(to_ogr([[(p[0], p[1]) for p in quad]]))
    geom.Segmentize(0.05)
    final[chart] = geom

# Coverage grid for the hole gate (0.5-cell tolerance so pixel-snapped
# edges mid-cell don't read as holes). Chopped insets DO report as holes
# by design — they are verified blank-on-purpose.
grid = np.zeros((GH, GW), bool)
for chart, polys in prechop.items():
    for poly in polys:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        gc0 = int(np.ceil((min(xs) - W0) / CELL - 0.5))
        gc1 = int(np.floor((max(xs) - W0) / CELL + 0.5))
        gr0 = int(np.ceil((min(ys) - S0) / CELL - 0.5))
        gr1 = int(np.floor((max(ys) - S0) / CELL + 0.5))
        grid[max(gr0, 0) : min(gr1, GH), max(gc0, 0) : min(gc1, GW)] = True

cov_row = np.zeros_like(grid)
cov_col = np.zeros_like(grid)
for ri in range(GH):
    idx = np.where(grid[ri])[0]
    if len(idx):
        cov_row[ri, idx.min() : idx.max() + 1] = True
for ci in range(GW):
    idx = np.where(grid[:, ci])[0]
    if len(idx):
        cov_col[idx.min() : idx.max() + 1, ci] = True
holes = (~grid) & cov_row & cov_col
hy, hx = np.where(holes)
print(f"holes (axis-enclosed, uncovered): {holes.sum()} cells")
clusters = {}
for y, x in zip(hy, hx):
    key = (round(W0 + x * CELL, 1) // 1, round(S0 + y * CELL, 1) // 1)
    clusters[key] = clusters.get(key, 0) + 1
for k in sorted(clusters):
    print(f"  ~({k[0]:.0f},{k[1]:.0f}): {clusters[k]} cells")

# emit cutline2 geojson (densified: gdalwarp rasterizes cutlines with
# straight chords in source LCC space; undensified parallels sag)
def densify(ring_pts):
    out = []
    for (a, b), (c, d) in zip(ring_pts, ring_pts[1:]):
        seg = max(abs(c - a), abs(d - b))
        n = max(1, int(seg / 0.05))
        for i in range(n):
            out.append([a + (c - a) * i / n, b + (d - b) * i / n])
    out.append(list(ring_pts[0]))
    return out

def repair(g):
    """Return a valid geometry, or None if it cannot be repaired."""
    if g is None or g.IsEmpty():
        return None
    if g.IsValid():
        return g
    for attempt in (lambda x: x.MakeValid(), lambda x: x.Buffer(0)):
        try:
            fixed = attempt(g)
        except Exception:
            continue
        if fixed is None or fixed.IsEmpty():
            continue
        if fixed.GetGeometryName() == "GEOMETRYCOLLECTION":
            mp = ogr.Geometry(ogr.wkbMultiPolygon)
            for i in range(fixed.GetGeometryCount()):
                part = fixed.GetGeometryRef(i)
                nm = part.GetGeometryName()
                if nm == "POLYGON":
                    mp.AddGeometry(part)
                elif nm == "MULTIPOLYGON":
                    for j in range(part.GetGeometryCount()):
                        mp.AddGeometry(part.GetGeometryRef(j))
            fixed = mp.UnionCascaded() if mp.GetGeometryCount() else None
        if fixed is not None and not fixed.IsEmpty() and fixed.IsValid():
            return fixed
    return None


prefill = {}

def roundtrip_ok(g):
    """Validate what we actually WRITE. A geometry can be valid in
    memory yet parse back invalid after GeoJSON coordinate rounding —
    which is exactly how 7 sheets reached gdalwarp as rejected cutlines
    while finalize reported success."""
    if g is None:
        return None
    js = g.ExportToJson()
    back = ogr.CreateGeometryFromJson(js)
    if back is not None and back.IsValid():
        return js
    fixed = repair(back) if back is not None else None
    if fixed is None:
        return None
    js2 = fixed.ExportToJson()
    again = ogr.CreateGeometryFromJson(js2)
    return js2 if (again is not None and again.IsValid()) else None


reverted = 0
for chart, geom in final.items():
    js = roundtrip_ok(repair(geom))
    if js is None and chart in prefill:
        # gap-fill made this sheet unwritable: ship the pre-fill
        # geometry (hairline gap) rather than a cutline gdalwarp drops.
        js = roundtrip_ok(repair(prefill[chart]))
        reverted += 1
    if js is None:
        raise SystemExit(f"{chart}: cutline geometry is invalid and unrepairable")
    geom = ogr.CreateGeometryFromJson(js)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"chart": chart},
                "geometry": json.loads(geom.ExportToJson()),
            }
        ],
    }
    json.dump(fc, open(units.unit_paths(chart)[2], "w"))
print(
    "wrote cutline2.geojson for", len(final), "charts"
    + (f" ({reverted} reverted to pre-gap-fill geometry)" if reverted else "")
)
