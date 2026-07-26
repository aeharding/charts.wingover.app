import math

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
ds = gdal.Open("/repo/data/conus/preview/conus.vrt")
gt = ds.GetGeoTransform()
for lon, lat in [(-124.5, 41.5), (-125.0, 41.5), (-124.0, 42.0), (-123.5, 41.0),
                 (-124.8, 40.5), (-122.5, 41.5), (-124.2, 43.5)]:
    X = lon * 20037508.342789244 / 180
    Y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137
    x = int((X - gt[0]) / gt[1])
    y = int((gt[3] - Y) / gt[1])
    a = ds.ReadAsArray(x, y, 1, 1)
    print(f"({lon},{lat}) alpha={int(a[3][0][0])} rgb={[int(a[i][0][0]) for i in range(3)]}")
