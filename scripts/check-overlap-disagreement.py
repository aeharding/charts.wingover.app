"""Find furniture by DISAGREEMENT: where two sheets chart the same ground,
they must show roughly the same picture.

This is the detector for the class that has now bitten three times and
was invisible to everything else: furniture inside a body cutline that
lands where ANOTHER sheet has real chart. Charlotte's FAA logo over the
Greer Class C, the St. Louis sheet's INDIANAPOLIS inset over northern
Arkansas (served at CVK), San Antonio's white margin over El Paso west
of Roy Hurd. The frame detector misses these, the furniture sweep only
renders EXPOSED area (a neighbour covers these by definition), and the
contact sheet shows them at a few hundred pixels where an inset looks
like any other city.

Method: for every pair of overlapping bodies, warp both over the
overlap and compare where both have data. Real chart vs real chart
disagrees only in generalization noise; chart vs inset, chart vs logo,
chart vs blank margin disagree massively over a large connected area.

Usage: python3 scripts/check-overlap-disagreement.py [region ...]
Reports blobs; exit 1 if any found. Runtime ~20-40 min for everything.
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

RES = 0.002          # deg per sample px (~220 m)
DIFF = 60.0          # mean |RGB| gap that counts as disagreement
MIN_DEG2 = 0.004     # blob area worth reporting
MIN_DIM = 0.02       # blob bbox min dimension: excludes seam hairlines
MAX_PX = 1400        # cap warp size per axis


def body(entry, region):
    _, _, cut = units.unit_paths(entry, region)
    if not os.path.exists(cut):
        return None
    return ogr.CreateGeometryFromJson(
        json.dumps(json.load(open(cut))["features"][0]["geometry"])
    )


def warp(entry, region, box, w, h):
    tif, vrt, cut = units.unit_paths(entry, region)
    if not os.path.exists(vrt):
        gdal.Translate(vrt, tif, format="VRT", rgbExpand="rgb")
    ds = gdal.Warp("", vrt, format="MEM", dstSRS="EPSG:4326",
                   outputBounds=box, width=w, height=h,
                   resampleAlg="average", dstAlpha=True, cutlineDSName=cut)
    return ds.ReadAsArray().astype(np.float32)


def blobs(mask, x0, y1, res):
    """Connected disagreement regions as (area, bbox) via flood fill
    (same approach as derive.py; the container has no scipy)."""
    seen = np.zeros_like(mask, dtype=bool)
    rows, cols = mask.shape
    out = []
    for r0 in range(rows):
        for c0 in range(cols):
            if not mask[r0, c0] or seen[r0, c0]:
                continue
            stack = [(r0, c0)]
            seen[r0, c0] = True
            minr = maxr = r0
            minc = maxc = c0
            n = 0
            while stack:
                y, x = stack.pop()
                n += 1
                minr, maxr = min(minr, y), max(maxr, y)
                minc, maxc = min(minc, x), max(maxc, x)
                for yy, xx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                    if 0 <= yy < rows and 0 <= xx < cols and mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
            area = n * res * res
            w = (maxc - minc + 1) * res
            h = (maxr - minr + 1) * res
            if area >= MIN_DEG2 and min(w, h) >= MIN_DIM:
                out.append((area,
                            (x0 + minc * res, y1 - (maxr + 1) * res,
                             x0 + (maxc + 1) * res, y1 - minr * res)))
    return out


def main(regions):
    cfg = json.load(open(f"{REPO}/regions.json"))
    regions = regions or list(cfg)
    allu = []
    for r in regions:
        for e in units.read_list(r):
            g = body(e, r)
            if g is not None:
                allu.append((r, e, g))

    findings = []
    pairs = 0
    for i, (ra, ea, ga) in enumerate(allu):
        for rb, eb, gb in allu[i + 1:]:
            inter = ga.Intersection(gb)
            if inter is None or inter.IsEmpty() or inter.GetArea() < 0.002:
                continue
            pairs += 1
            x0, x1, y0, y1 = inter.GetEnvelope()
            # Pixels MUST stay square: blobs() converts px to degrees with
            # one factor for both axes. The old max(64,...) floor on h
            # stretched thin-strip overlaps (Cape Lisburne x Nome came out
            # 2.02x tall), so reported latitudes were wrong and one box
            # landed 0.2 deg outside the sheet entirely.
            wpx = max(64, int((x1 - x0) / RES))
            scale = min(1.0, MAX_PX / wpx)
            w = int(wpx * scale)
            rx = (x1 - x0) / w
            h = max(8, round((y1 - y0) / rx))
            try:
                a = warp(ea, ra, (x0, y0, x1, y1), w, h)
                b = warp(eb, rb, (x0, y0, x1, y1), w, h)
            except RuntimeError as exc:
                print(f"  warp failed {ea} x {eb}: {exc}", file=sys.stderr)
                continue
            both = (a[-1] > 0) & (b[-1] > 0)
            if both.sum() < 100:
                continue
            diff = np.abs(a[:3] - b[:3]).mean(axis=0)
            mask = both & (diff > DIFF)
            hits = blobs(mask, x0, y1, rx)
            print(f"  [{pairs:3d}] {ea} x {eb}: {len(hits)} blob(s)", flush=True)
            for area, bx in hits:
                findings.append((area, ra, ea, rb, eb, bx))

    findings.sort(reverse=True)
    print(f"\n{pairs} overlapping pairs compared")
    if findings:
        print(f"OVERLAP DISAGREEMENT: {len(findings)} blob(s)")
        for area, ra, ea, rb, eb, bx in findings:
            print(f"  {area:7.3f} deg2  {ra}/{ea}  x  {rb}/{eb}")
            print(f"           box [{bx[0]:.3f}, {bx[1]:.3f}, {bx[2]:.3f}, {bx[3]:.3f}]")
        return 1
    print("overlap disagreement OK: overlapping sheets agree everywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
