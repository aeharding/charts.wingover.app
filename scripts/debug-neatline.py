import os

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
chart = "Los_Angeles"
d = f"/repo/data/conus/src/{chart}"
tif = [f for f in os.listdir(d) if f.lower().endswith(".tif")][0]
src = gdal.Open(os.path.join(d, tif))
W0, H0 = src.RasterXSize, src.RasterYSize
dw, dh = W0 // 8, H0 // 8
rgb = gdal.Translate("", src, format="VRT", rgbExpand="rgb")
a = rgb.ReadAsArray(0, 0, W0, H0, buf_xsize=dw, buf_ysize=dh)
print("decimated", dw, dh, "bands", a.shape[0])
for thresh in (120, 170, 200):
    dark = np.minimum(np.minimum(a[0], a[1]), a[2]) < thresh
    colf = dark.mean(axis=0)
    rowf = dark.mean(axis=1)
    print(f"thresh {thresh}: max col frac {colf.max():.2f} at {int(colf.argmax())}, "
          f"max row frac {rowf.max():.2f} at {int(rowf.argmax())}, "
          f"cols>0.5 {int((colf>0.5).sum())}, rows>0.5 {int((rowf>0.5).sum())}")
# where are the strongest columns?
dark = np.minimum(np.minimum(a[0], a[1]), a[2]) < 170
colf = dark.mean(axis=0)
top = np.argsort(colf)[-12:]
print("top cols:", sorted((int(c), round(float(colf[c]), 2)) for c in top))
rowf = dark.mean(axis=1)
topr = np.argsort(rowf)[-12:]
print("top rows:", sorted((int(r), round(float(rowf[r]), 2)) for r in topr))
