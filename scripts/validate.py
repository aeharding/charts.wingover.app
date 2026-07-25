# Cutline validation, geo-space: sample points a fixed geographic inset
# inside each cutline edge. A correct cut shows opaque chart colors there;
# collar leakage shows dominant near-white; a sagging/short cut shows
# transparent samples. Works regardless of warp envelope padding or the
# neat line's tilt in projected space.
import glob
import json
import os

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
INSET = 0.03  # degrees inside the edge
N = 200

t4326 = osr.SpatialReference()
t4326.ImportFromEPSG(4326)
t4326.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
t3857 = osr.SpatialReference()
t3857.ImportFromEPSG(3857)
to3857 = osr.CoordinateTransformation(t4326, t3857)

for path in sorted(glob.glob("/repo/data/conus/warped/*.tif")):
    name = os.path.basename(path)[:-4]
    cut = json.load(open(f"/repo/data/conus/src/{name}/cutline.geojson"))
    ring = cut["features"][0]["geometry"]["coordinates"][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    w, s, e, n = min(xs), min(ys), max(xs), max(ys)
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    inv = gdal.InvGeoTransform(gt)
    flags = []
    edges = {
        "W": [(w + INSET, s + INSET + (n - s - 2 * INSET) * i / N) for i in range(N)],
        "E": [(e - INSET, s + INSET + (n - s - 2 * INSET) * i / N) for i in range(N)],
        "S": [(w + INSET + (e - w - 2 * INSET) * i / N, s + INSET) for i in range(N)],
        "N": [(w + INSET + (e - w - 2 * INSET) * i / N, n - INSET) for i in range(N)],
    }
    for edge, pts in edges.items():
        vals = []
        transparent = 0
        for lon, lat in pts:
            X, Y = to3857.TransformPoint(lon, lat)[:2]
            px, py = gdal.ApplyGeoTransform(inv, X, Y)
            px, py = int(px), int(py)
            if not (0 <= px < ds.RasterXSize and 0 <= py < ds.RasterYSize):
                transparent += 1
                continue
            d = ds.ReadAsArray(px, py, 1, 1).reshape(-1)
            if len(d) > 3 and d[3] == 0:
                transparent += 1
            else:
                vals.append(d[:3])
        if transparent > N * 0.1:
            flags.append(f"{edge}:transparent{transparent * 100 // N}%")
        if vals:
            a = np.array(vals)
            white = ((a[:, 0] > 235) & (a[:, 1] > 235) & (a[:, 2] > 235)).mean()
            if white > 0.5:
                flags.append(f"{edge}:white{white:.0%}")
    print(f"{name:28} {'OK' if not flags else '  '.join(flags)}")
