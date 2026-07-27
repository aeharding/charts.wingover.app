"""Render every unit of a region into one contact sheet, for eyeballing.

The automated furniture check in audit-units.py is whiteness-based and
has a proven blind spot: it missed San Francisco's legend block entirely
because the terrain tint ramp is COLOURED, not white. Detecting printed
marginalia reliably is harder than looking at it, and there are only 59
units, so this renders them all at a size where a legend panel or an
inset mini-map is an obvious rectangle.

Usage: python3 scripts/contact-sheet.py <region> [cell-px]
Writes data/<region>/contact.png
"""

import json
import math
import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

import numpy as np  # noqa: E402
from osgeo import gdal  # noqa: E402

import units  # noqa: E402


gdal.UseExceptions()


def main(region, cell=700):
    entries = units.read_list(region)
    n = len(entries)
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = int(math.ceil(n / cols))
    sheet = np.full((3, rows * cell, cols * cell), 30, np.uint8)

    for i, entry in enumerate(entries):
        tif, vrt, cut = units.unit_paths(entry, region)
        if not os.path.exists(tif):
            continue
        if not os.path.exists(vrt):
            gdal.Translate(vrt, tif, format="VRT", rgbExpand="rgb")
        try:
            ds = gdal.Warp(
                "", vrt, format="MEM", dstSRS="EPSG:3857",
                width=cell, height=cell, resampleAlg="average",
                dstAlpha=True, cutlineDSName=cut, cropToCutline=True,
            )
        except RuntimeError as exc:
            print(f"  {entry}: {exc}", file=sys.stderr)
            continue
        a = ds.ReadAsArray()
        r, c = divmod(i, cols)
        y, x = r * cell, c * cell
        h, w = a.shape[1], a.shape[2]
        sheet[:, y:y + h, x:x + w] = a[:3, :, :]
        print(f"  {i:3d} {entry}")

    out = gdal.GetDriverByName("MEM").Create(
        "", cols * cell, rows * cell, 3, gdal.GDT_Byte
    )
    for b in range(3):
        out.GetRasterBand(b + 1).WriteArray(sheet[b])
    os.makedirs(f"{REPO}/data/{region}", exist_ok=True)
    path = f"{REPO}/data/{region}/contact.png"
    gdal.GetDriverByName("PNG").CreateCopy(path, out)
    print(f"wrote {path}: {cols}x{rows} cells of {cell}px, {n} units")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 700))
