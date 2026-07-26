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

import numpy as np
from osgeo import ogr

ogr.UseExceptions()

CELL = 1 / 12
DATA = "/repo/data/conus/dataregions.json"
regions = json.load(open(DATA))

W0, S0, E0, N0 = -127, 23, -60, 50
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

for chart, geom in final.items():
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
    json.dump(fc, open(f"/repo/data/conus/src/{chart}/cutline2.geojson", "w"))
print("wrote cutline2.geojson for", len(final), "charts")
