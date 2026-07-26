import math

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
ds = gdal.Open("/repo/data/conus/preview/conus.vrt")
gt = ds.GetGeoTransform()

def px(lon, lat):
    X = lon * 20037508.342789244 / 180
    Y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137
    return int((X - gt[0]) / gt[1]), int((gt[3] - Y) / gt[1])

def lonlat(x, y):
    X = gt[0] + x * gt[1]
    Y = gt[3] - y * gt[1]
    return X / 20037508.342789244 * 180, math.degrees(math.atan(math.sinh(Y / 6378137)))

for name, (w, n, e, s) in {
    "mendocino": (-126.4, 39.8, -124.8, 38.4),
    "conception": (-122.6, 35.4, -121.2, 34.2),
}.items():
    x0, y0 = px(w, n)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = px(e, s)
    a = ds.ReadAsArray(x0, y0, x1 - x0, y1 - y0)
    opq = a[3] > 0
    ys, xs = np.where(opq)
    if not len(xs):
        print(name, "empty")
        continue
    lo1, la1 = lonlat(x0 + xs.min(), y0 + ys.min())
    lo2, la2 = lonlat(x0 + xs.max(), y0 + ys.max())
    print(f"{name}: content lon {lo1:.3f}..{lo2:.3f} lat {la2:.3f}..{la1:.3f} px={int(opq.sum())}")
