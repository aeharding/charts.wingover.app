# Automated seam scanner: sweep the mosaic for WHITE strips and
# TRANSPARENT slits that have map content on both sides — the artifact
# signature of a bad joint. Zero findings (outside the intentional inset
# chop boxes) is the exit criterion for stitch work.
import json
import math
import sys

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
ds = gdal.Open("/repo/data/conus/preview/conus.vrt")
gt = ds.GetGeoTransform()
W, H = ds.RasterXSize, ds.RasterYSize

def to_lon(px):
    return (gt[0] + px * gt[1]) / 20037508.342789244 * 180

def to_lat(py):
    return math.degrees(math.atan(math.sinh((gt[3] - py * gt[1]) / 6378137)))

# Known intentional chops (from insets.json detection results; padded).
CHOPS = [
    (-122.3, 31.8, -119.9, 33.7),
    (-87.2, 28.2, -85.7, 29.8),
    (-84.9, 28.1, -83.6, 29.4),
    (-79.9, 30.8, -78.3, 32.4),
    (-73.2, 36.6, -71.7, 37.9),
]

def in_chop(lon, lat):
    return any(w <= lon <= e and s <= lat <= n for w, s, e, n in CHOPS)

findings = []
# Contiguity-based: a stitch seam is an UNBROKEN white (or transparent)
# vertical run with map on both sides for hundreds of km; natural white
# (playas, printed blanks) never sustains that. Track, per column, the
# longest consecutive run of seam-condition rows.
BAND = 512
cur_run_w = np.zeros(W, np.int64)
best_run_w = np.zeros(W, np.int64)
best_end_w = np.zeros(W, np.int64)
cur_run_t = np.zeros(W, np.int64)
best_run_t = np.zeros(W, np.int64)
best_end_t = np.zeros(W, np.int64)
for y0 in range(0, H, BAND):
    h = min(BAND, H - y0)
    a = ds.ReadAsArray(0, y0, W, h)
    opq = a[3] > 0
    whit = (a[0] > 245) & (a[1] > 245) & (a[2] > 245) & opq
    mapv = opq & ~((a[0] > 242) & (a[1] > 242) & (a[2] > 242))
    def shifted(m, d):
        out = np.zeros_like(m)
        if d > 0:
            out[:, d:] = m[:, :-d]
        else:
            out[:, :d] = m[:, -d:]
        return out
    both = (
        shifted(mapv, 30) & shifted(mapv, -30)
        & shifted(mapv, 60) & shifted(mapv, -60)
    )
    seamw = whit & both
    seamt = (~opq) & both
    for rr in range(h):
        y = y0 + rr
        for cur, best, bend, m in (
            (cur_run_w, best_run_w, best_end_w, seamw[rr]),
            (cur_run_t, best_run_t, best_end_t, seamt[rr]),
        ):
            cur[m] += 1
            cur[~m] = 0
            upd = cur > best
            best[upd] = cur[upd]
            bend[upd] = y

for kind, best, bend in (
    ("WHITE", best_run_w, best_end_w),
    ("GAP", best_run_t, best_end_t),
):
    x = 0
    while x < W:
        if best[x] > 500:  # ~200 km unbroken
            x1 = x
            while x1 + 1 < W and best[x1 + 1] > 250:
                x1 += 1
            pk = x + int(np.argmax(best[x : x1 + 1]))
            lon = to_lon(pk)
            run = int(best[pk])
            lat1 = to_lat(bend[pk])
            lat0 = to_lat(bend[pk] - run)
            if not in_chop(lon, (lat0 + lat1) / 2):
                findings.append(
                    (kind, round(lon, 3), round(lat1, 2), round(lat0, 2), run, x1 - x + 1)
                )
            x = x1 + 40
        x += 1

for f in findings:
    print("SEAM", f)
print("total findings:", len(findings))

# Horizontal sweep: same contiguity logic transposed (row-wise), for
# tier-joint seams the column sweep is blind to.
cur_run_w = np.zeros(H, np.int64)
best_run_w = np.zeros(H, np.int64)
best_end_w = np.zeros(H, np.int64)
cur_run_t = np.zeros(H, np.int64)
best_run_t = np.zeros(H, np.int64)
best_end_t = np.zeros(H, np.int64)
CBAND = 512
for x0 in range(0, W, CBAND):
    wch = min(CBAND, W - x0)
    a = ds.ReadAsArray(x0, 0, wch, H)
    opq = a[3] > 0
    whit = (a[0] > 245) & (a[1] > 245) & (a[2] > 245) & opq
    mapv = opq & ~((a[0] > 242) & (a[1] > 242) & (a[2] > 242))
    def vshift(m, d):
        out = np.zeros_like(m)
        if d > 0:
            out[d:, :] = m[:-d, :]
        else:
            out[:d, :] = m[-d:, :]
        return out
    both = (
        vshift(mapv, 30) & vshift(mapv, -30)
        & vshift(mapv, 60) & vshift(mapv, -60)
    )
    seamw = whit & both
    seamt = (~opq) & both
    for cc in range(wch):
        x = x0 + cc
        for cur, best, bend, m in (
            (cur_run_w, best_run_w, best_end_w, seamw[:, cc]),
            (cur_run_t, best_run_t, best_end_t, seamt[:, cc]),
        ):
            cur[m] += 1
            cur[~m] = 0
            upd = cur > best
            best[upd] = cur[upd]
            bend[upd] = x

hfindings = []
for kind, best, bend in (
    ("HWHITE", best_run_w, best_end_w),
    ("HGAP", best_run_t, best_end_t),
):
    y = 0
    while y < H:
        if best[y] > 500:
            y1 = y
            while y1 + 1 < H and best[y1 + 1] > 250:
                y1 += 1
            pk = y + int(np.argmax(best[y : y1 + 1]))
            lat = to_lat(pk)
            run = int(best[pk])
            lon1 = to_lon(bend[pk])
            lon0 = to_lon(bend[pk] - run)
            if not in_chop((lon0 + lon1) / 2, lat):
                hfindings.append((kind, round(lat, 3), round(lon0, 2), round(lon1, 2), run, y1 - y + 1))
            y = y1 + 40
        y += 1

for f in hfindings:
    print("SEAM", f)
print("horizontal findings:", len(hfindings))

# non-zero exit so CI can gate on it
if findings or hfindings:
    sys.exit(1)
