"""Locate printed furniture a unit still exposes, as seed points.

audit-units.py says a unit has margin furniture nothing covers; this says
WHERE, in coordinates you can paste into insets.json. San Francisco's
elevation legend sits in the Pacific with no neighbour over it, and there
was no insets.json entry for it at all.

Reports connected near-white blobs in the part of the unit's body that no
other unit covers, largest first, with a seed point and a bounding box.

Usage: python3 scripts/find-furniture.py <region> <unit entry>
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

WHITE = 242
RES = 0.004          # degrees per sample pixel, ~440 m
MIN_DEG2 = float(os.environ.get("MIN_DEG2", "0.02"))  # ignore specks


def body(entry, region):
    _, _, cut = units.unit_paths(entry, region)
    return ogr.CreateGeometryFromJson(
        json.dumps(json.load(open(cut))["features"][0]["geometry"])
    )


def main(region, entry):
    cfg = json.load(open(f"{REPO}/regions.json"))
    g = body(entry, region)
    for r in cfg:
        for other in units.read_list(r):
            if (r, other) == (region, entry):
                continue
            _, _, cut = units.unit_paths(other, r)
            if not os.path.exists(cut):
                continue
            og = body(other, r)
            if og is not None and g.Intersects(og):
                g = g.Difference(og)
    if g is None or g.IsEmpty():
        print("nothing exposed")
        return 0

    x0, x1, y0, y1 = g.GetEnvelope()
    w, h = int((x1 - x0) / RES), int((y1 - y0) / RES)
    gdal.FileFromMemBuffer(
        "/vsimem/exposed.geojson",
        json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {},
                          "geometry": json.loads(g.ExportToJson())}],
        }),
    )
    _, vrt, _ = units.unit_paths(entry, region)
    ds = gdal.Warp(
        "", vrt, format="MEM", dstSRS="EPSG:4326",
        outputBounds=(x0, y0, x1, y1), width=w, height=h,
        resampleAlg="average", dstAlpha=True,
        cutlineDSName="/vsimem/exposed.geojson",
    )
    a = ds.ReadAsArray()
    white = (a[:3] > WHITE).all(axis=0) & (a[-1] > 0)

    # Iterative flood fill, the same way derive.py finds components: the
    # GDAL container has no scipy, and adding a dependency for one label
    # pass is not worth it.
    seen = np.zeros_like(white, dtype=bool)
    rows, cols = white.shape
    blobs = []
    for r0 in range(rows):
        for c0 in range(cols):
            if not white[r0, c0] or seen[r0, c0]:
                continue
            stack = [(r0, c0)]
            seen[r0, c0] = True
            minr = maxr = r0
            minc = maxc = c0
            count = 0
            while stack:
                y, x = stack.pop()
                count += 1
                minr, maxr = min(minr, y), max(maxr, y)
                minc, maxc = min(minc, x), max(maxc, x)
                for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= yy < rows and 0 <= xx < cols and white[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
            area = count * RES * RES
            if area < MIN_DEG2:
                continue
            bx0, bx1 = x0 + minc * RES, x0 + (maxc + 1) * RES
            by1, by0 = y1 - minr * RES, y1 - (maxr + 1) * RES
            blobs.append((area, bx0, by0, bx1, by1))
    blobs.sort(reverse=True)

    if not blobs:
        print(f"{region}/{entry}: no exposed white blobs over {MIN_DEG2} deg2")
        return 0
    print(f"{region}/{entry}: {len(blobs)} exposed white blob(s)")
    for area, bx0, by0, bx1, by1 in blobs[:6]:
        print(
            f'  {{"sheet": "...", "seed": [{(bx0 + bx1) / 2:.2f}, '
            f'{(by0 + by1) / 2:.2f}], "box": [{bx0:.2f}, {by0:.2f}, '
            f'{bx1:.2f}, {by1:.2f}]}}   area {area:.2f} deg2'
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
