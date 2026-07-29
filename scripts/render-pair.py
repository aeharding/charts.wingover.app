"""Render two sheets side by side over one box, for disagreement triage.

check-overlap-disagreement.py says two sheets disagree in a box; this
shows WHAT each sheet puts there, labelled, in one image. Disagreement
has three causes with three different verdicts:

  furniture   one side is an inset/logo/blank margin -> chop it
  edition     both are real chart but different chart EDITIONS (a new
              tower or airspace amendment on one sheet only) -> keep
  seam noise  generalization differences at a join -> keep

Usage: python3 scripts/render-pair.py <regA> <unitA> <regB> <unitB> \\
         <x0> <y0> <x1> <y1> <out.png>
"""

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

PAD = 0.06   # context beyond the blob box
W = 1000     # px per panel


def render(entry, region, box):
    tif, vrt, cut = units.unit_paths(entry, region)
    if not os.path.exists(vrt):
        gdal.Translate(vrt, tif, format="VRT", rgbExpand="rgb")
    h = int(W * (box[3] - box[1]) / (box[2] - box[0]))
    ds = gdal.Warp("", vrt, format="MEM", dstSRS="EPSG:4326",
                   outputBounds=box, width=W, height=h,
                   resampleAlg="average", dstAlpha=True, cutlineDSName=cut)
    a = ds.ReadAsArray()
    rgb = a[:3].astype(np.uint8).copy()
    # transparent -> mid grey so "no data" is distinguishable from white
    rgb[:, a[-1] == 0] = 128
    return rgb


def main(ra, ea, rb, eb, x0, y0, x1, y1, out):
    box = (x0 - PAD, y0 - PAD, x1 + PAD, y1 + PAD)
    a = render(ea, ra, box)
    b = render(eb, rb, box)
    h = min(a.shape[1], b.shape[1])
    gap = np.zeros((3, h, 12), np.uint8)
    combo = np.concatenate([a[:, :h, :], gap, b[:, :h, :]], axis=2)
    # mark the blob box on both panels (red outline)
    def mark(px_off):
        fx0 = int((x0 - box[0]) / (box[2] - box[0]) * W) + px_off
        fx1 = int((x1 - box[0]) / (box[2] - box[0]) * W) + px_off
        fy0 = int((box[3] - y1) / (box[3] - box[1]) * h)
        fy1 = int((box[3] - y0) / (box[3] - box[1]) * h)
        fy0, fy1 = max(0, fy0), min(h - 1, fy1)
        fx0c, fx1c = max(0, fx0), min(combo.shape[2] - 1, fx1)
        combo[0, fy0:fy1, fx0c] = 255; combo[1:, fy0:fy1, fx0c] = 0
        combo[0, fy0:fy1, fx1c] = 255; combo[1:, fy0:fy1, fx1c] = 0
        combo[0, fy0, fx0c:fx1c] = 255; combo[1:, fy0, fx0c:fx1c] = 0
        combo[0, fy1, fx0c:fx1c] = 255; combo[1:, fy1, fx0c:fx1c] = 0
    mark(0)
    mark(W + 12)
    o = gdal.GetDriverByName("MEM").Create("", combo.shape[2], h, 3, gdal.GDT_Byte)
    for i in range(3):
        o.GetRasterBand(i + 1).WriteArray(combo[i])
    gdal.GetDriverByName("PNG").CreateCopy(out, o)
    print(f"wrote {out}  LEFT={ra}/{ea}  RIGHT={rb}/{eb}")
    print(f"  grey = that sheet has no data there; red outline = the disagreement blob")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0], a[1], a[2], a[3],
                  float(a[4]), float(a[5]), float(a[6]), float(a[7]), a[8]))
