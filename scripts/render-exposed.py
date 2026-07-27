"""Render the part of a unit that NO other unit covers, for furniture review.

Printed furniture only matters where nothing draws over it: every sheet
carries a "Joins <neighbour>" ruler and a legend block, but on interior
sheets the neighbours cover them. San Francisco's legend lands in the
Pacific because nothing is west of it.

Two modes:

  render   python3 scripts/render-exposed.py <region> <unit> [out.png] [px]
           the whole exposed area, printing the bbox and px-per-degree so
           pixel positions in the image convert straight to lon/lat

  crop     python3 scripts/render-exposed.py <region> <unit> --crop \\
             <x0> <y0> <x1> <y1> [out.png]
           just that lon/lat box, to CHECK a candidate chop contains only
           furniture before it goes in insets.json. Chopping real chart is
           worse than leaving the furniture.
"""

import json
import os
import sys

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, f"{REPO}/scripts")

from osgeo import gdal, ogr  # noqa: E402

import units  # noqa: E402


gdal.UseExceptions()
ogr.UseExceptions()


def body(entry, region):
    _, _, cut = units.unit_paths(entry, region)
    if not os.path.exists(cut):
        return None
    return ogr.CreateGeometryFromJson(
        json.dumps(json.load(open(cut))["features"][0]["geometry"])
    )


def exposed(region, entry):
    g = body(entry, region)
    if g is None:
        raise SystemExit(f"no cutline for {region}/{entry}; derive it first")
    cfg = json.load(open(f"{REPO}/regions.json"))
    for r in cfg:
        for other in units.read_list(r):
            if (r, other) == (region, entry):
                continue
            og = body(other, r)
            if og is not None and g.Intersects(og):
                g = g.Difference(og)
                if g is None or g.IsEmpty():
                    raise SystemExit(f"{region}/{entry} is fully covered")
    return g


def main(argv):
    region, entry = argv[0], argv[1]
    g = exposed(region, entry)
    gdal.FileFromMemBuffer(
        "/vsimem/exposed.geojson",
        json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {},
                          "geometry": json.loads(g.ExportToJson())}],
        }),
    )
    _, vrt, _ = units.unit_paths(entry, region)
    tif, _, _ = units.unit_paths(entry, region)
    if not os.path.exists(vrt):
        gdal.Translate(vrt, tif, format="VRT", rgbExpand="rgb")

    if "--crop" in argv:
        i = argv.index("--crop")
        x0, y0, x1, y1 = (float(v) for v in argv[i + 1:i + 5])
        out = argv[i + 5] if len(argv) > i + 5 else "/repo/data/crop.png"
        width = 1400
    else:
        x0, x1, y0, y1 = g.GetEnvelope()
        out = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else "/repo/data/exposed.png"
        width = int(argv[3]) if len(argv) > 3 else 1400

    ds = gdal.Warp(
        "", vrt, format="MEM", dstSRS="EPSG:4326",
        outputBounds=(x0, y0, x1, y1),
        width=width, height=int(width * (y1 - y0) / (x1 - x0)),
        resampleAlg="average", dstAlpha=True,
        cutlineDSName="/vsimem/exposed.geojson",
    )
    gdal.GetDriverByName("PNG").CreateCopy(out, ds)
    ppd = width / (x1 - x0)
    print(f"wrote {out}")
    print(f"  lon {x0:.4f} .. {x1:.4f}   lat {y0:.4f} .. {y1:.4f}")
    print(f"  size {ds.RasterXSize}x{ds.RasterYSize}   {ppd:.1f} px per degree")
    print(f"  lon = {x0:.4f} + px_x / {ppd:.1f}")
    print(f"  lat = {y1:.4f} - px_y / {ppd:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
