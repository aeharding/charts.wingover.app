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
    strict_orig = strict.copy()
    # BRIDGE narrow gaps (1-2 cells) before component analysis: sheets
    # print "Joins <neighbor>" ruler strips MID-CHART with white
    # backing, and the printed map continues ~0.7 deg beyond them
    # (visible in 1800wxbrief: map content between the ruler and their
    # seam). The ruler's white column split our component and the
    # overedge beyond it was orphaned and discarded — manufacturing
    # fake abutting joints (Cheyenne/Omaha at 101W) with unfillable
    # gaps. Panels are ~1 deg (12 cells) wide and stay unbridged.
    base = strict.copy()
    for gap in (1, 2, 3):
        strict[:, gap:-gap] |= base[:, : -2 * gap] & base[:, 2 * gap :]
        strict[gap:-gap, :] |= base[: -2 * gap, :] & base[2 * gap :, :]
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
    # per column: FULL span (first..last body cell) — but only when the
    # column is mostly body. Interior white islands (salt flats, playas)
    # ride inside dense columns and are kept; a SPARSE column (isolated
    # collar-CORNER cells passing the classifier where rulers cross)
    # must not be span-filled into a full-height collar strip (Memphis
    # west shipped a 2-cell collar slab spanning 32N-36N this way) —
    # sparse columns collapse to their largest contiguous run.
    spans = []
    for ci in range(cols):
        idx = np.where(body[:, ci])[0]
        if not len(idx):
            spans.append((0, 0))
            continue
        t, b = int(idx.min()), int(idx.max()) + 1
        if len(idx) >= 0.4 * (b - t):
            spans.append((t, b))
            continue
        best_s = best_e = run_s = prev = int(idx[0])
        for v in idx[1:]:
            v = int(v)
            if v != prev + 1:
                if prev + 1 - run_s > best_e - best_s:
                    best_s, best_e = run_s, prev + 1
                run_s = v
            prev = v
        if prev + 1 - run_s > best_e - best_s:
            best_s, best_e = run_s, prev + 1
        spans.append((best_s, best_e))
    # TRUE SIDE EDGES: sheets are rectangular in their native LCC, so a
    # side margin is a TILTED line here — it wanders across 2-3 columns
    # over the sheet's height, and any column it crosses carries a white
    # margin fraction that would paint over the neighbor (the diagonal
    # slash west of PQI). Mark the outermost 3 columns per side as YIELD
    # columns: finalize keeps one only where NO other sheet covers it —
    # dropped at interior joints (deep overlap covers), kept at true
    # rims (Matinicus Isle sits in New York's east yield columns with no
    # Halifax coverage below 44N; cutting it unconditionally clipped the
    # island). Interior (panel-adjacent) group edges are never yielded.
    valid_cols = [ci for ci in range(cols) if spans[ci][1] - spans[ci][0] > 2]
    yield_cols = set()
    if valid_cols:
        yield_cols.update(range(valid_cols[0], min(valid_cols[0] + 3, cols)))
        yield_cols.update(range(max(valid_cols[-1] - 2, 0), valid_cols[-1] + 1))
    # RULER COLUMNS: a column whose span exists mostly through bridging
    # is a printed Joins-ruler (white-backed) — never paint it over the
    # neighbor's clean overedge map. Excluded from the body like yields;
    # the neighboring sheet's overedge fills the strip, so the stitch is
    # fully continuous with no white ruler bands at any joint. (Interior
    # white islands like Bonneville enter spans by span-fill, not
    # bridging, and stay: their bridge-added fraction is tiny.)
    for ci in range(cols):
        t, b = spans[ci]
        if b - t <= 2 or ci in yield_cols:
            continue
        added = int((~strict_orig[t:b, ci] & strict[t:b, ci]).sum())
        if added > 0.5 * (b - t):
            yield_cols.add(ci)

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
    # med() is NaN-aware for its WINDOW, but must never RESURRECT an
    # empty column: filling a NaN column from its neighbors emitted two
    # phantom full-height margin columns at every sheet edge — the
    # ~14 px white strips the seam scanner kept finding at -95.1, -77.1,
    # -102.1... Smooth valid columns only.
    invalid = np.isnan(ftop) | np.isnan(fbot)
    ftop = med(ftop)
    fbot = med(fbot)
    ftop[invalid] = np.nan
    fbot[invalid] = np.nan
    # SIDE (yield) columns are emitted as per-5-minute-band rects whose
    # outer x edge is SNAPPED TO INK, scanned from outside the sheet
    # inward: coverage then runs from the printed edge (the outermost
    # Joins-ruler tick) to the body, carrying map and ruler but NEVER
    # white margin. Kept sides at abutting joints thus butt the
    # neighbor's ink the way 1800wxbrief's stitch does; the margin bands
    # that painted "massive regular seams" across the US are gone.
    side_polys = []
    Wpx = cols * PX
    if valid_cols:
        left = sorted(c for c in yield_cols if c <= valid_cols[0] + 2)
        right = sorted(c for c in yield_cols if c >= valid_cols[-1] - 2)
        for group, is_left in ((left, True), (right, False)):
            if not group:
                continue
            ref = max(group) if is_left else min(group)
            if np.isnan(ftop[ref]) or np.isnan(fbot[ref]):
                continue
            inner_x = w + ((max(group) + 1) if is_left else min(group)) * CELL
            top_r = max(int(round((n - ftop[ref]) / RES)), 0)
            bot_r = min(int(round((n - fbot[ref]) / RES)), H)
            for bi in range(top_r // PX, (bot_r + PX - 1) // PX):
                r0 = max(bi * PX, top_r)
                r1 = min((bi + 1) * PX, bot_r)
                if r1 - r0 < PX // 3:
                    continue
                # SUSTAINED ink (8 consecutive columns), same as the
                # row snap: a single col_ink hit latched onto the
                # sheet's outer FRAME LINE and included the whole margin
                # as a white strip down every west edge (the 9-seam
                # scanner sweep). Map is continuously inky; the frame
                # stroke is 2-3 px.
                SRUN = 8
                if is_left:
                    x_edge = None
                    run = 0
                    for xx in range(max((min(group) - 1) * PX, 0), (max(group) + 1) * PX):
                        run = run + 1 if col_ink(xx, r0, r1) else 0
                        if run == SRUN:
                            x_edge = w + (xx - SRUN + 1) * RES
                            break
                    if x_edge is None or x_edge >= inner_x:
                        continue
                    rect = (x_edge, n - r1 * RES, inner_x, n - r0 * RES)
                else:
                    x_edge = None
                    run = 0
                    for xx in range(min((max(group) + 2) * PX, Wpx) - 1, min(group) * PX - 1, -1):
                        run = run + 1 if col_ink(xx, r0, r1) else 0
                        if run == SRUN:
                            x_edge = w + (xx + SRUN) * RES
                            break
                    if x_edge is None or x_edge <= inner_x:
                        continue
                    rect = (inner_x, n - r1 * RES, x_edge, n - r0 * RES)
                x0r, y0r, x1r, y1r = rect
                side_polys.append(
                    [[x0r, y0r], [x1r, y0r], [x1r, y1r], [x0r, y1r], [x0r, y0r]]
                )
    return w, n, cols, ftop, fbot, yield_cols, side_polys

def emit(chart, w, n, cols, ftop, fbot, skip=frozenset()):
    # merge columns with equal (RES-quantized) snapped spans into slabs
    slabs = []
    for ci in range(cols):
        if ci in skip or np.isnan(ftop[ci]) or np.isnan(fbot[ci]):
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

# INSET DETECTION: printed addendum boxes (mini-maps, rule diagrams)
# float over ocean inside the map region and must be chopped. Each is
# configured as just a SEED coordinate inside the box (insets.json) so a
# future edition moving or resizing the box still detects, and a box
# that vanishes fails the bake loudly instead of shipping garbage.
# Method: warp a window around the seed near source resolution, find the
# nearest long horizontal border stroke above the seed, walk its extent
# to the corners, and verify all four sides close as dark rectangle
# borders.
def detect_inset(chart, seed_lon, seed_lat):
    """Find the printed addendum box around a seed coordinate.

    Works in the SOURCE SCAN's pixel space: the box is a true rectangle
    there (sheets and their insets are rectangular in native LCC, tilted
    in geographic space — an axis-aligned detector in lon/lat can never
    match, which is how v1 of this failed). After the border rectangle
    is found, the surrounding white margin band is absorbed by walking
    outward until printed content resumes, so the whole addendum
    footprint is chopped, then the corners transform to lon/lat and the
    bounding box (plus the margin, which comfortably absorbs the tilt)
    is returned."""
    from osgeo import osr

    d = os.path.join(SRC, chart)
    tif = [f for f in os.listdir(d) if f.lower().endswith(".tif")][0]
    src = gdal.Open(os.path.join(d, tif))
    rgb = gdal.Translate("", src, format="VRT", rgbExpand="rgb")
    gt = src.GetGeoTransform()
    inv = gdal.InvGeoTransform(gt)
    srs = src.GetSpatialRef()
    wgs = osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_src = osr.CoordinateTransformation(wgs, srs)
    to_geo = osr.CoordinateTransformation(srs, wgs)
    X, Y = to_src.TransformPoint(seed_lon, seed_lat)[:2]
    spx, spy = gdal.ApplyGeoTransform(inv, X, Y)
    spx, spy = int(spx), int(spy)
    HW = 2800  # window half-size in source px (~2.4 deg boxes + margin)
    x0 = max(spx - HW, 0)
    y0 = max(spy - HW, 0)
    ww = min(spx + HW, src.RasterXSize) - x0
    hh = min(spy + HW, src.RasterYSize) - y0
    a = rgb.ReadAsArray(x0, y0, ww, hh)
    # stroke = decidedly non-white ink: the Eglin box border is RED, so
    # "dark" alone misses it; min-channel < 160 catches black, red, and
    # blue strokes while paper, ocean tint, and pale map fills stay out.
    dark = np.minimum(np.minimum(a[0], a[1]), a[2]) < 160
    white = np.minimum(np.minimum(a[0], a[1]), a[2]) > 235
    sy, sx = spy - y0, spx - x0
    Hh, Ww = dark.shape

    # The box is aligned to the printed PAPER while the raster grid is
    # the LCC projection: borders drift ~1 px per 100 along their
    # length (measured 24 px over the Eglin box height). Wide any()
    # bands prefilter cheaply; a re-centering line FOLLOWER verifies,
    # tracking the drift by construction.
    def hcov(rr, c0, c1, hw=1):
        return dark[max(rr - hw, 0) : rr + hw + 1, c0:c1].any(axis=0).mean()

    def vcov(cc, r0, r1, hw=1):
        return dark[r0:r1, max(cc - hw, 0) : cc + hw + 1].any(axis=1).mean()

    # Followers SEEK wide (±20 px) until first anchored, then track
    # tight (±4): the paper-vs-grid drift means a border can sit ~18 px
    # off the nominal row at the far end of the box (Eglin's top border
    # left half), and a fixed tight window never acquires it.
    def follow_v(cc, r0, r1):
        ok = total = 0
        c = cc
        hw = 20
        for r in range(r0, r1, 2):
            lo = max(c - hw, 0)
            seg = dark[r, lo : c + hw + 1]
            total += 1
            if seg.any():
                ok += 1
                xs = np.where(seg)[0] + lo
                c = int(xs[np.argmin(np.abs(xs - c))])
                hw = 4
        return ok / max(total, 1)

    def follow_h(rr, c0, c1):
        ok = total = 0
        r = rr
        hw = 20
        for c in range(c0, c1, 2):
            lo = max(r - hw, 0)
            seg = dark[lo : r + hw + 1, c]
            total += 1
            if seg.any():
                ok += 1
                ys = np.where(seg)[0] + lo
                r = int(ys[np.argmin(np.abs(ys - r))])
                hw = 4
        return ok / max(total, 1)

    def extmean(sl):
        return float(sl.mean()) if sl.size > 200 else 0.0

    def extcheck(rt, rb, cl, cr):
        # The decisive test: a REAL inset border has the white margin
        # band OUTSIDE all four sides; content rectangles have dense
        # chart ink out there. Bands sit 12-28 px out, beyond stroke
        # width plus paper-vs-grid drift; off-raster bands pass (the
        # box may be flush with the sheet edge).
        ext = (
            extmean(dark[max(rt - 28, 0) : max(rt - 12, 1), cl + 10 : cr - 10]),
            extmean(dark[rb + 12 : min(rb + 28, Hh), cl + 10 : cr - 10]),
            extmean(dark[rt + 10 : rb - 10, max(cl - 28, 0) : max(cl - 12, 1)]),
            extmean(dark[rt + 10 : rb - 10, cr + 12 : min(cr + 28, Ww)]),
        )
        # one side may host an adjacent chart graticule line (Eglin's
        # bottom hugs the 28-30' parallel: ~0.15); content rectangles
        # are dirty on several sides
        v = sorted(ext)
        return v[-1] < 0.25 and v[-2] < 0.12

    K = 40
    MIN_PX = 700  # inset boxes are ~0.6 deg (1000 src px) at minimum
    # Candidate rows are tested at three windows, not just over the
    # seed column: mini-map titles are printed ON the top border line
    # (LOS ANGELES BASIN breaks it dead-center, right where a centered
    # seed looks).
    CAND_OFFSETS = (0, -600, 600)
    for rt in range(sy, 1, -1):  # nearest long stroke above the seed
        if not any(
            hcov(rt, max(sx + off - 2 * K, 0), min(sx + off + 2 * K, Ww)) > 0.9
            for off in CAND_OFFSETS
        ):
            continue
        # cheap pre-filter: a real top border has near-empty margin
        # above it; content rows (dense ink above) die here before the
        # expensive candidate walks
        if (
            extmean(dark[max(rt - 28, 0) : max(rt - 12, 1),
                         max(sx - 600, 0) : min(sx + 600, Ww)])
            > 0.15
        ):
            continue

        def vrun(cc):
            return vcov(cc, rt + 3, min(rt + 900, Hh), hw=8) > 0.85

        # Candidate verticals OUTWARD from the seed, several per side:
        # diagram interiors (Eglin's MOA boxes) contain their own
        # bordered rectangles, so the nearest stroke is often not the
        # box side. Wrong pairs self-reject: an interior line cannot
        # span the box's full height.
        def vcands(step):
            # only margin-backed verticals qualify: the band just
            # outside a real border is white margin, while a straight
            # city street inside a mini-map has dense ink there — the
            # 12-slot cap otherwise fills with urban grid lines long
            # before the search reaches the true edge (Los Angeles).
            out = []
            r1 = min(rt + 900, Hh)
            cc = sx
            while 1 < cc < Ww - 2 and len(out) < 12:
                cc += step
                if vrun(cc):
                    if step < 0:
                        m = dark[rt + 3 : r1, max(cc - 28, 0) : max(cc - 12, 1)].mean()
                    else:
                        m = dark[rt + 3 : r1, cc + 12 : min(cc + 28, Ww)].mean()
                    if m < 0.12:
                        out.append(cc)
                    cc += step * 25  # skip past this stroke either way
            if not out:
                # edge-flush box: the border runs off the scanned sheet
                # (Los Angeles Basin inset is flush with the sheet's
                # west edge). The raster edge IS the border then.
                out.append(8 if step < 0 else Ww - 9)
            return out

        closed = None
        for cl in vcands(-1):
            for cr in vcands(1):
                if cr - cl < MIN_PX:
                    continue
                if hcov(rt, cl + 10, cr - 10, hw=14) <= 0.9:
                    continue
                # validate the top by halves so a centered title
                # breaking the stroke cannot fail a genuine border
                mid = (cl + cr) // 2
                if not (
                    follow_h(rt, cl + 10, cr - 10) > 0.8
                    or (
                        follow_h(rt, cl + 10, max(mid - 500, cl + 11)) > 0.85
                        and follow_h(rt, min(mid + 500, cr - 11), cr - 10) > 0.85
                    )
                ):
                    continue
                # iterate candidate bottoms UNCAPPED and lazily: in a
                # content-dense inset (LA basin) thousands of interior
                # rows look line-like, and any fixed candidate cap fills
                # before the true border 3000+ rows down. Cheap
                # vectorized tests run first; content rows die on the
                # below-band exterior check in one op.
                rb = None
                r = rt + MIN_PX
                while r < Hh:
                    if hcov(r, cl + 10, cr - 10, hw=14) > 0.9:
                        below = extmean(
                            dark[r + 12 : min(r + 28, Hh), cl + 10 : cr - 10]
                        )
                        if (
                            below < 0.25
                            and follow_h(r, cl + 10, cr - 10) > 0.8
                            # edge-flush sides (at the raster boundary)
                            # validate trivially: their stroke is off-sheet
                            and (cl <= 10 or follow_v(cl, rt + 10, r - 10) > 0.8)
                            and (
                                cr >= Ww - 11
                                or follow_v(cr, rt + 10, r - 10) > 0.8
                            )
                            and extcheck(rt, r, cl, cr)
                        ):
                            rb = r
                            break
                        # skip just past this stroke: a 30px skip once
                        # jumped clean over the true border when content
                        # ended within 30px of it (LA basin)
                        r += 6
                    r += 1
                if rb is None:
                    continue
                closed = (cl, cr, rb)
                break
                # The decisive test: a REAL inset border has the white
                # margin band OUTSIDE all four sides. Content rectangles
                # inside a busy mini-map (which pass every line test)
                # have dense chart ink out there instead. Bands sit
                # 12-28 px out, beyond stroke width plus paper-vs-grid
                # drift.

            if closed:
                break
        if not closed:
            continue
        cl, cr, rb = closed
        # absorb the white margin band around the box (the printed
        # addendum includes it; stopping at the border would leave a
        # white halo in the mosaic). Walk until printed content resumes.
        def wrow(rr, c0, c1):
            return white[rr, c0:c1].mean() > 0.7

        def wcol(cc, r0, r1):
            return white[r0:r1, cc].mean() > 0.7

        # The walk also HOPS thin content bands (up to ~70 px) when
        # white resumes beyond: the addendum's title and scale-bar strip
        # sits outside the border box separated by white, and stopping
        # at the scale bar left TAMPA/JACKSONVILLE strips in the mosaic.
        def absorb(pos, step, is_row, lo_lim, hi_lim, c0, c1):
            hops = 0
            probe = wrow if is_row else wcol
            while True:
                while lo_lim < pos < hi_lim and (
                    probe(pos + 2 * step, c0, c1)
                ):
                    pos += step
                if hops >= 3:
                    return pos
                jump = None
                for d in range(4, 72):
                    q = pos + d * step
                    if not (lo_lim < q < hi_lim):
                        break
                    if probe(q, c0, c1) and probe(q + 6 * step, c0, c1):
                        jump = q
                        break
                if jump is None:
                    return pos
                pos = jump
                hops += 1

        rt2 = absorb(rt, -1, True, 1, Hh - 2, cl, cr)
        rb2 = absorb(rb, 1, True, 1, Hh - 2, cl, cr)
        cl2 = absorb(cl, -1, False, 1, Ww - 2, rt2, rb2)
        cr2 = absorb(cr, 1, False, 1, Ww - 2, rt2, rb2)
        # corners -> lon/lat; bbox (the tilt overshoot is far smaller
        # than the absorbed margin, so bbox cannot clip real map)
        lons, lats = [], []
        for px, py in ((cl2, rt2), (cr2, rt2), (cr2, rb2), (cl2, rb2)):
            Xc, Yc = gdal.ApplyGeoTransform(gt, x0 + px, y0 + py)
            lon, lat = to_geo.TransformPoint(Xc, Yc)[:2]
            lons.append(lon)
            lats.append(lat)
        box = (min(lons), min(lats), max(lons), max(lats))
        # a box that does not contain its seed means the seed was
        # misplaced and the detector latched onto a neighboring
        # rectangle — fail loudly rather than chop the wrong thing
        if not (box[0] <= seed_lon <= box[2] and box[1] <= seed_lat <= box[3]):
            raise RuntimeError(
                f"inset detection for {chart} found a box {box} that does "
                f"not contain its seed ({seed_lon},{seed_lat}); re-seed "
                "insets.json inside the box"
            )
        return box
    # RuntimeError, not SystemExit: SystemExit inside a Pool worker
    # kills the worker silently and the pool hangs forever waiting.
    raise RuntimeError(
        f"inset detection FAILED for {chart} seed ({seed_lon},{seed_lat}); "
        "re-seed insets.json for this edition"
    )

INSETS_PATH = os.path.join(os.path.dirname(SRC), "..", "..", "insets.json")
INSETS = json.load(open(INSETS_PATH)) if os.path.exists(INSETS_PATH) else []

def one(chart):
    w, n, cols, ftop, fbot, yield_cols, side = detect(chart)
    polys = emit(chart, w, n, cols, ftop, fbot, skip=yield_cols)
    insets = [
        tuple(entry["box"]) if "box" in entry else detect_inset(chart, *entry["seed"])
        for entry in INSETS
        if entry["sheet"] == chart
    ]
    # summary: overall data bbox + slab count
    xs = [p for poly in polys for p, _ in poly]
    ys = [q for poly in polys for _, q in poly]
    line = (
        f"{chart:22} data [{min(xs):9.4f},{min(ys):8.4f} .. {max(xs):9.4f},{max(ys):8.4f}]"
        f"  slabs={len(polys)} yield={len(side)} insets={len(insets)}"
    )
    return chart, {"polys": polys, "side": side, "insets": insets}, line

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
        for chart, region, line in pool.imap(one, charts):
            print(line, flush=True)
            out[chart] = region

    json.dump(out, open("/repo/data/conus/dataregions.json", "w"))
    print("wrote dataregions.json")
