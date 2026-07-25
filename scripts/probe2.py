import numpy as np
from osgeo import gdal
gdal.UseExceptions()
SRC = "/repo/data/conus/src"; RES = 0.00125
def stats(chart, w, s, e, n, label):
    mem = gdal.Warp("", gdal.Translate("", f"{SRC}/{chart}/rgb.vrt", format="VRT"),
        format="MEM", dstSRS="EPSG:4326", dstAlpha=True,
        outputBounds=(w, s, e, n), xRes=RES, yRes=RES, resampleAlg="near")
    a = mem.ReadAsArray().astype(np.int16)
    r, g, b, al = a[0], a[1], a[2], a[3]; m = al > 0
    if m.sum() == 0: print(f"{label:38} EMPTY"); return
    r, g, b = r[m], g[m], b[m]
    def wf(t): return ((r > t) & (g > t) & (b > t)).mean()
    print(f"{label:38} white>235={wf(235):.2f} >240={wf(240):.2f} >242={wf(242):.2f} >245={wf(245):.2f} medRGB=({np.median(r):.0f},{np.median(g):.0f},{np.median(b):.0f})")
# Collar strips (degree labels) and legend panels: v3-minus-v2 areas.
stats("Chicago", -89.5, 44.35, -89.0, 44.55, "Chicago N collar (degrees)")
stats("Dallas-Ft_Worth", -102.3, 33.0, -102.05, 34.0, "Dallas W legend panel")
stats("San_Antonio", -103.7, 29.0, -103.1, 30.0, "San Antonio W legend panel")
stats("Denver", -111.7, 37.0, -111.1, 38.0, "Denver W legend panel")
stats("New_York", -77.8, 41.0, -77.1, 42.0, "New York W legend panel")
stats("Chicago", -88.0, 40.0, -87.5, 40.4, "Chicago farmland (map, control)")
