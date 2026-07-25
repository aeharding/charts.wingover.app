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
    # 242, not 235 — measured (probe-cells.py, 2026-07-25): the palest
    # low-elevation map tint (St. Lawrence lowlands, Gulf coastal plain,
    # interior Maine) sits at RGB 236-240, while panel/collar/legend
    # paper is pure 255. At 235 the pale tint counted as white and whole
    # coastal plains were amputated (the v2 bug); at 242 pale map cells
    # measure 0.02-0.08 white and paper measures 0.86-1.00 — a clean
    # margin on both sides. An ink-saturation OR-branch was tried first
    # and re-admitted legend swatches and collars wholesale; threshold
    # separation makes it unnecessary.
    white = ((r > 242) & (g > 242) & (b > 242)).mean(axis=(1, 3))
    # texture: mean abs horizontal gradient over the cell
    grad = (
        np.abs(np.diff(a[0], axis=1)) + np.abs(np.diff(a[1], axis=1)) + np.abs(np.diff(a[2], axis=1))
    )
    grad = grad[: rows * PX, : cols * PX - 1]
    tex = np.zeros((rows, cols))
    for ci in range(cols):
        seg = grad[:, ci * PX : (ci + 1) * PX - 1]
        tex[:, ci] = (seg > 30).reshape(rows, PX, -1).mean(axis=(1, 2))
    # Measured discriminator: map content is never white-dominant (even
    # its palest tint is 236-240, and desert bg is TAN 248/228/174 —
    # tan fails the b-channel — water blue, cities yellow) while
    # panels/collars/title blocks are 255-paper (0.86-1.00 white).
    # Texture cannot separate the two (sparse desert 0.07 < panel text
    # 0.31) and is not used.
    strict = (opaque > 0.9) & (white < 0.5)
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
    # TRUE SIDE EDGES: sheets are rectangular in their native LCC, so a
    # side margin is a TILTED line here — it wanders across 2-3 columns
    # over the sheet's height, and any column it crosses carries a white
    # margin fraction that would paint over the neighbor (the diagonal
    # slash west of PQI). Side joints overlap 15-30+ minutes, so simply
    # drop 3 columns from each outermost group edge and let the
    # neighbor's pure map cover; the hole gate verifies no pairing got
    # too thin. Interior (panel-adjacent) group edges keep their
    # columns — their neighbor margins are thin.
    valid_cols = [ci for ci in range(cols) if spans[ci][1] - spans[ci][0] > 2]
    if valid_cols:
        for ci in range(valid_cols[0], min(valid_cols[0] + 3, cols)):
            spans[ci] = (0, 0)
        for ci in range(max(valid_cols[-1] - 2, 0), valid_cols[-1] + 1):
            spans[ci] = (0, 0)

    # PIXEL-PRECISE NEATLINE SNAP. Cell-granular edges caused every
    # boundary artifact so far: the cell straddling the printed neatline
    # is half map / half collar, so either it drops (notches along the
    # 49N rim) or it ships collar ink that mosaic order then paints over
    # a neighbor's real map (the 44°30' tier joint, the Montreal-Halifax
    # meridian). Instead of arbitrating cells, snap each edge to the ink
    # itself: scan pixel rows from one cell beyond the detected span
    # inward and cut where ink actually starts (a row is "ink" when its
    # opaque pixels are majority non-white — sparse collar text like the
    # 30' labels never reaches majority). Overlapping sheets then both
    # carry pure map, and mosaic order stops mattering.
    whitefull = (a[0] > 242) & (a[1] > 242) & (a[2] > 242)
    opqfull = a[3] > 0
    def row_ink(rr, x0, x1):
        opq = opqfull[rr, x0:x1]
        if opq.mean() < 0.5:
            return False
        return whitefull[rr, x0:x1][opq].mean() < 0.5
    def col_ink(xx, r0, r1):
        opq = opqfull[r0:r1, xx]
        if opq.mean() < 0.5:
            return False
        return whitefull[r0:r1, xx][opq].mean() < 0.5
    # RETREAT pulls every snapped edge a few pixels INSIDE the ink: the
    # neatline stroke and the warp's antialiased edge row then land in
    # the neighbor's overedge overlap instead of painting over its map
    # as a hairline. ~50 m of printed margin lost at true rims —
    # invisible.
    RETREAT = 4
    # SUSTAINED ink only: a single solid stroke must not stop the scan —
    # the sheet frame is outer-border-line, then a mostly-white graticule
    # tick strip with degree labels, then the neatline; stopping at the
    # first inky row captured that whole collar band (the 100°/30' strip
    # over Pierre). The map body is continuously inky, so demand RUN
    # consecutive ink rows and snap to the run's start.
    RUN = 8
    H = rows * PX
    ftop = np.full(cols, np.nan)
    fbot = np.full(cols, np.nan)
    for ci, (t, b) in enumerate(spans):
        if b - t <= 2:  # degenerate column (< 10 min of data)
            continue
        x0, x1 = ci * PX, (ci + 1) * PX
        lo, hi = max((t - 1) * PX, 0), min((t + 1) * PX, H)
        top_px = t * PX
        run = 0
        for rr in range(lo, hi):
            run = run + 1 if row_ink(rr, x0, x1) else 0
            if run == RUN:
                top_px = rr - RUN + 1
                break
        lo, hi = max((b - 1) * PX, 0), min((b + 1) * PX, H)
        bot_px = b * PX
        run = 0
        for rr in range(hi - 1, lo - 1, -1):
            run = run + 1 if row_ink(rr, x0, x1) else 0
            if run == RUN:
                bot_px = rr + RUN
                break
        ftop[ci] = n - (top_px + RETREAT) * RES
        fbot[ci] = n - (bot_px - RETREAT) * RES
    # smooth per-column jitter (rolling median, window 5): neatlines are
    # constant-latitude, so the median flattens pixel noise and keeps
    # real steps (Denver's Grand Canyon corner).
    def med(v):
        out = v.copy()
        for i in range(len(v)):
            win = v[max(0, i - 2) : i + 3]
            win = win[~np.isnan(win)]
            if len(win):
                out[i] = np.median(win)
        return out
    ftop = med(ftop)
    fbot = med(fbot)
    return w, n, cols, ftop, fbot

def emit(chart, w, n, cols, ftop, fbot):
    # merge columns with equal (RES-quantized) snapped spans into slabs
    slabs = []
    for ci in range(cols):
        if np.isnan(ftop[ci]) or np.isnan(fbot[ci]):
            continue
        span = (round(ftop[ci] / RES), round(fbot[ci] / RES))
        if slabs and slabs[-1][1] == ci and slabs[-1][2] == span:
            slabs[-1] = (slabs[-1][0], ci + 1, span)
        else:
            slabs.append((ci, ci + 1, span))
    polys = []
    for c0, c1, (t, b) in slabs:
        x0 = w + c0 * CELL
        x1 = w + c1 * CELL
        polys.append([[x0, b * RES], [x1, b * RES], [x1, t * RES], [x0, t * RES], [x0, b * RES]])
    return polys

def one(chart):
    w, n, cols, ftop, fbot = detect(chart)
    polys = emit(chart, w, n, cols, ftop, fbot)
    # summary: overall data bbox + slab count
    xs = [p for poly in polys for p, _ in poly]
    ys = [q for poly in polys for _, q in poly]
    line = f"{chart:22} data [{min(xs):9.4f},{min(ys):8.4f} .. {max(xs):9.4f},{max(ys):8.4f}]  slabs={len(polys)}"
    return chart, polys, line

if __name__ == "__main__":
    from multiprocessing import Pool

    # The chart list is EXPLICIT (charts.txt at the repo root, one sheet
    # per line). v2 selected by the presence of a leftover v1 cutline
    # file, which is how sheet-list drift went unnoticed. A listed chart
    # missing from src/ is a hard failure, never a silent skip.
    charts = [
        line.strip()
        for line in open(os.path.join(os.path.dirname(SRC), "..", "..", "charts.txt"))
        if line.strip() and not line.startswith("#")
    ]
    missing = [c for c in charts if not os.path.isdir(os.path.join(SRC, c))]
    if missing:
        raise SystemExit(f"charts.txt entries missing from {SRC}: {missing}")
    out = {}
    # Each worker holds one sheet's full-res detection warp (~0.5 GB);
    # six keep a 12-core box busy without pressuring 30 GB of RAM.
    with Pool(min(6, os.cpu_count() or 1)) as pool:
        for chart, polys, line in pool.imap(one, charts):
            print(line, flush=True)
            out[chart] = polys

    json.dump(out, open("/repo/data/conus/dataregions.json", "w"))
    print("wrote dataregions.json")
