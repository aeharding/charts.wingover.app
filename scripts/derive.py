# Cutline derivation v2: the cutline IS the detected map-data region.
# Per chart: warp once to a coarse geographic grid in memory, classify
# 1/12-degree cells as map-data (textured, non-white) vs panel/collar
# (white legend panels, uniform color bars, blank margins), then emit a
# rectilinear stepped polygon per chart from the per-column data spans.
# No nominal quadrangles in the output; FGDC bbox is only the scan area.
import json
import os
import re

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
SRC = "/repo/data/conus/src"
RES = 0.00125        # warp grid (deg/px) — fine enough that thin contour
                     # lines survive nearest sampling (sparse desert charts
                     # have no other texture)
CELL = 1 / 12        # detection cell (5 minutes)
PX = round(CELL / RES)  # px per cell edge

def fgdc_bbox(d):
    htm = [f for f in os.listdir(d) if f.lower().endswith(".htm")][0]
    raw = open(os.path.join(d, htm), "rb").read()
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            t = raw.decode(enc)
            break
        except Exception:
            continue
    t = re.sub(r"<[^>]+>", " ", t)
    def grab(tag):
        m = re.search(tag + r"_Bounding_Coordinate:\s*(-?\d+\.?\d*)", t)
        return float(m.group(1))
    return grab("West"), grab("South"), grab("East"), grab("North")

def snap(v, up):
    k = round(v / CELL)
    return (np.ceil(v / CELL) if up else np.floor(v / CELL)) / (1 / CELL) if abs(k * CELL - v) > 1e-9 else v

def detect(chart):
    d = os.path.join(SRC, chart)
    w, s, e, n = fgdc_bbox(d)
    # snap scan window outward to the cell grid
    w = np.floor(w / CELL) * CELL
    s = np.floor(s / CELL) * CELL
    e = np.ceil(e / CELL) * CELL
    n = np.ceil(n / CELL) * CELL
    tif = [f for f in os.listdir(d) if f.lower().endswith(".tif")][0]
    rgb = gdal.Translate("", os.path.join(d, tif), format="VRT", rgbExpand="rgb")
    mem = gdal.Warp(
        "", rgb, format="MEM", dstSRS="EPSG:4326", dstAlpha=True,
        outputBounds=(w, s, e, n), xRes=RES, yRes=RES, resampleAlg="near",
    )
    a = mem.ReadAsArray().astype(np.int16)  # (4, H, W), row 0 = north
    _, H, W = a.shape
    cols = W // PX
    rows = H // PX
    a = a[:, : rows * PX, : cols * PX]
    # cell tensors
    r = a[0].reshape(rows, PX, cols, PX)
    g = a[1].reshape(rows, PX, cols, PX)
    b = a[2].reshape(rows, PX, cols, PX)
    alpha = a[3].reshape(rows, PX, cols, PX)
    opaque = (alpha > 0).mean(axis=(1, 3))
    white = ((r > 235) & (g > 235) & (b > 235)).mean(axis=(1, 3))
    # ink: fraction of clearly SATURATED pixels (channel spread). Chart
    # ink is colored — magenta airspace, blue water, brown contours,
    # yellow towns — while panel/collar content is black text on white
    # paper (spread ~0). This is what rescues pale low-elevation map
    # areas (Gulf coastal plain, St. Lawrence lowlands, interior Maine):
    # their background tint crosses the white threshold cell-wide, but
    # the aeronautical overprint is always present. Printed-blank
    # foreign interior (Mexico, s. Ontario paper at 240/240/242) stays
    # excluded: near-zero spread, near-zero ink.
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    ink = ((mx - mn) > 25).mean(axis=(1, 3))
    # texture: mean abs horizontal gradient over the cell
    grad = (
        np.abs(np.diff(a[0], axis=1)) + np.abs(np.diff(a[1], axis=1)) + np.abs(np.diff(a[2], axis=1))
    )
    grad = grad[: rows * PX, : cols * PX - 1]
    tex = np.zeros((rows, cols))
    for ci in range(cols):
        seg = grad[:, ci * PX : (ci + 1) * PX - 1]
        tex[:, ci] = (seg > 30).reshape(rows, PX, -1).mean(axis=(1, 2))
    # Measured discriminator (probes 2026-07-24): map content is never
    # white-dominant (desert bg is TAN 248/228/174, water blue, cities
    # yellow) while panels/collars/title blocks are white-backed
    # (0.90-1.00). Texture cannot separate the two (sparse desert 0.07 <
    # panel text 0.31) and is not used. The ink OR-branch (v3) admits
    # white-dominant cells that still carry colored overprint — the
    # pale-lowland amputation bug (Brownsville coast, Montreal north of
    # 45N, Halifax west of -66.75) shipped without it. Panel legend
    # swatches are also inked, but they rejoin as small components and
    # the largest-component step below orphans them as before.
    strict = (opaque > 0.9) & ((white < 0.5) | (ink > 0.02))
    # Largest connected component = the sheet's map body. Panel color
    # swatches and collar decorations become small orphan components and
    # drop out; everything tan/blue/green stays connected through the map.
    label = np.full((rows, cols), -1, int)
    best_id, best_size = -1, 0
    cur = 0
    for ri in range(rows):
        for ci in range(cols):
            if strict[ri, ci] and label[ri, ci] < 0:
                stack = [(ri, ci)]
                label[ri, ci] = cur
                size = 0
                while stack:
                    y, x = stack.pop()
                    size += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < rows and 0 <= xx < cols and strict[yy, xx] and label[yy, xx] < 0:
                            label[yy, xx] = cur
                            stack.append((yy, xx))
                if size > best_size:
                    best_id, best_size = cur, size
                cur += 1
    body = label == best_id
    # opening (erode+dilate by 1): shaves single-cell boundary fuzz where
    # a cell straddles the panel/map junction
    er = body.copy()
    er[1:] &= body[:-1]; er[:-1] &= body[1:]
    er[:, 1:] &= body[:, :-1]; er[:, :-1] &= body[:, 1:]
    di = er.copy()
    di[1:] |= er[:-1]; di[:-1] |= er[1:]
    di[:, 1:] |= er[:, :-1]; di[:, :-1] |= er[:, 1:]
    body = di
    # per column: FULL span (first..last body cell). Interior white
    # islands (salt flats, playas) are inside the span and thus kept.
    spans = []
    for ci in range(cols):
        idx = np.where(body[:, ci])[0]
        spans.append((int(idx.min()), int(idx.max()) + 1) if len(idx) else (0, 0))
    return w, n, cols, rows, spans

def emit(chart, w, n, cols, spans):
    # rectilinear polygon from per-column [top,bottom) spans (cell coords)
    # -> merge columns with identical spans into vertical slabs
    slabs = []
    for ci, (t, b) in enumerate(spans):
        if b - t <= 2:  # skip degenerate columns (< 10 min of data)
            continue
        if slabs and slabs[-1][1] == ci and slabs[-1][2] == (t, b):
            slabs[-1] = (slabs[-1][0], ci + 1, (t, b))
        else:
            slabs.append((ci, ci + 1, (t, b)))
    polys = []
    for c0, c1, (t, b) in slabs:
        x0 = w + c0 * CELL
        x1 = w + c1 * CELL
        y1 = n - t * CELL
        y0 = n - b * CELL
        polys.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]])
    return polys

out = {}
# The chart list is EXPLICIT (charts.txt at the repo root, one sheet per
# line). v2 selected by the presence of a leftover v1 cutline file, which
# is how sheet-list drift went unnoticed. A listed chart that is missing
# from src/ is a hard failure, never a silent skip.
charts = [
    line.strip()
    for line in open(os.path.join(os.path.dirname(SRC), "..", "..", "charts.txt"))
    if line.strip() and not line.startswith("#")
]
missing = [c for c in charts if not os.path.isdir(os.path.join(SRC, c))]
if missing:
    raise SystemExit(f"charts.txt entries missing from {SRC}: {missing}")
for chart in charts:
    w, n, cols, rows, spans = detect(chart)
    polys = emit(chart, w, n, cols, spans)
    # summary: overall data bbox + slab count
    xs = [p for poly in polys for p, _ in poly]
    ys = [q for poly in polys for _, q in poly]
    print(f"{chart:22} data [{min(xs):9.4f},{min(ys):8.4f} .. {max(xs):9.4f},{max(ys):8.4f}]  slabs={len(polys)}")
    out[chart] = polys

json.dump(out, open("/repo/data/conus/dataregions.json", "w"))
print("wrote dataregions.json")
