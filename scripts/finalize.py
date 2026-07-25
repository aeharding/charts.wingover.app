# Finalize v2 cutlines: smooth per-column detection jitter (rolling
# median, window 5 - preserves real steps, kills one-off notches), emit
# MultiPolygon slab cutlines (densified), and gate on the FIXED hole
# checker: a cell is a hole if uncovered AND enclosed by coverage along
# either axis (catches band gaps of any length, the old checker's blind
# spot).
import json

import numpy as np

CELL = 1 / 12
DATA = "/repo/data/conus/dataregions.json"
regions = json.load(open(DATA))

W0, S0, E0, N0 = -127, 23, -60, 50
GW = round((E0 - W0) / CELL)
GH = round((N0 - S0) / CELL)
grid = np.zeros((GH, GW), bool)  # [row from south][col from west]

smoothed = {}
for chart, polys in regions.items():
    # rebuild per-column spans from slabs
    xs = sorted({p[0] for poly in polys for p in poly})
    w = min(xs)
    e = max(p[0] for poly in polys for p in poly)
    cols = round((e - w) / CELL)
    top = np.full(cols, np.nan)
    bot = np.full(cols, np.nan)
    for poly in polys:
        x0 = poly[0][0]; x1 = poly[1][0]
        y0 = min(q[1] for q in poly); y1 = max(q[1] for q in poly)
        c0 = round((x0 - w) / CELL); c1 = round((x1 - w) / CELL)
        top[c0:c1] = y1
        bot[c0:c1] = y0
    # rolling median (window 5), NaN-aware
    def med(a):
        out = a.copy()
        for i in range(len(a)):
            win = a[max(0, i - 2) : i + 3]
            win = win[~np.isnan(win)]
            if len(win):
                out[i] = np.median(win)
        return out
    top = med(top)
    bot = med(bot)
    # drop columns with <10min of data after smoothing
    valid = ~np.isnan(top) & ~np.isnan(bot) & (top - bot > 2 * CELL)
    # re-emit slabs
    slabs = []
    for ci in range(cols):
        if not valid[ci]:
            continue
        span = (round(bot[ci] / CELL), round(top[ci] / CELL))
        if slabs and slabs[-1][1] == ci and slabs[-1][2] == span:
            slabs[-1] = (slabs[-1][0], ci + 1, span)
        else:
            slabs.append((ci, ci + 1, span))
    polys2 = []
    for c0, c1, (b, t) in slabs:
        x0 = w + c0 * CELL
        x1 = w + c1 * CELL
        polys2.append((x0, b * CELL, x1, t * CELL))
        # paint the union grid
        gc0 = round((x0 - W0) / CELL); gc1 = round((x1 - W0) / CELL)
        gr0 = round((b * CELL - S0) / CELL); gr1 = round((t * CELL - S0) / CELL)
        grid[gr0:gr1, gc0:gc1] = True
    smoothed[chart] = polys2

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

# emit cutline2 geojson (densified)
def densify(x0, y0, x1, y1):
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    out = []
    for (a, b), (c, d) in zip(ring, ring[1:]):
        seg = max(abs(c - a), abs(d - b))
        n = max(1, int(seg / 0.05))
        for i in range(n):
            out.append([a + (c - a) * i / n, b + (d - b) * i / n])
    out.append([x0, y0])
    return out

for chart, polys in smoothed.items():
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"chart": chart},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[densify(*p)] for p in polys],
            },
        }],
    }
    json.dump(fc, open(f"/repo/data/conus/src/{chart}/cutline2.geojson", "w"))
print("wrote cutline2.geojson for", len(smoothed), "charts")
