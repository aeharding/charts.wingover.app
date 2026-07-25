# Finalize cutlines: hole-gate the union coverage and emit densified
# MultiPolygon cutlines per sheet.
#
# Deliberately thin. derive.py snaps every region edge to the printed
# neatline at pixel precision (~140 m) and median-smooths per column, so
# regions contain no collar ink and overlapping sheets carry identical
# map imagery — no cross-sheet arbitration is needed and mosaic order
# cannot matter. (Three generations of cell-granular arbitration died
# here; see derive.py's neatline-snap comment for the artifact history.)
import json

import numpy as np

CELL = 1 / 12
DATA = "/repo/data/conus/dataregions.json"
regions = json.load(open(DATA))

W0, S0, E0, N0 = -127, 23, -60, 50
GW = round((E0 - W0) / CELL)
GH = round((N0 - S0) / CELL)

# Coverage grid for the hole gate: a cell counts as covered when a
# region overlaps most of it (0.5 cell margin), so pixel-snapped edges
# that sit mid-cell don't read as holes.
grid = np.zeros((GH, GW), bool)
for chart, polys in regions.items():
    for poly in polys:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        gc0 = int(np.ceil((x0 - W0) / CELL - 0.5))
        gc1 = int(np.floor((x1 - W0) / CELL + 0.5))
        gr0 = int(np.ceil((y0 - S0) / CELL - 0.5))
        gr1 = int(np.floor((y1 - S0) / CELL + 0.5))
        grid[max(gr0, 0) : min(gr1, GH), max(gc0, 0) : min(gc1, GW)] = True

# hole check: uncovered cell enclosed along a row or a column
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
def densify(ring):
    out = []
    for (a, b), (c, d) in zip(ring, ring[1:]):
        seg = max(abs(c - a), abs(d - b))
        n = max(1, int(seg / 0.05))
        for i in range(n):
            out.append([a + (c - a) * i / n, b + (d - b) * i / n])
    out.append(list(ring[0]))
    return out

for chart, polys in regions.items():
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"chart": chart},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[densify([tuple(p) for p in poly])] for poly in polys],
            },
        }],
    }
    json.dump(fc, open(f"/repo/data/conus/src/{chart}/cutline2.geojson", "w"))
print("wrote cutline2.geojson for", len(regions), "charts")
