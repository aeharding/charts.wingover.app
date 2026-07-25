# Empirical classifier probe: pixel statistics over chosen lon/lat
# windows, warped exactly like derive.py's detection grid. Used to set
# thresholds from measurements instead of guesses.
import json
import sys

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
SRC = "/repo/data/conus/src"
RES = 0.00125

def stats(chart, w, s, e, n, label):
    rgb = gdal.Translate("", f"{SRC}/{chart}/rgb.vrt", format="VRT")
    mem = gdal.Warp("", rgb, format="MEM", dstSRS="EPSG:4326", dstAlpha=True,
                    outputBounds=(w, s, e, n), xRes=RES, yRes=RES, resampleAlg="near")
    a = mem.ReadAsArray().astype(np.int16)
    r, g, b, al = a[0], a[1], a[2], a[3]
    m = al > 0
    if m.sum() == 0:
        print(f"{label:34} EMPTY")
        return
    r, g, b = r[m], g[m], b[m]
    sat = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    def wf(t): return ((r > t) & (g > t) & (b > t)).mean()
    print(f"{label:34} white>235={wf(235):.2f} >240={wf(240):.2f} >245={wf(245):.2f} >250={wf(250):.2f}  sat>25={(sat>25).mean():.3f} sat>12={(sat>12).mean():.3f} medRGB=({np.median(r):.0f},{np.median(g):.0f},{np.median(b):.0f})")

# Pale map areas that v2 wrongly amputated (must be INCLUDED):
stats("Montreal", -73.8, 45.3, -73.4, 45.7, "Montreal lowland (map, pale)")
stats("Montreal", -70.4, 46.0, -70.0, 46.4, "Maine interior (map, pale)")
stats("Brownsville", -97.6, 26.5, -97.2, 26.9, "S Texas plain (map, pale)")
stats("Halifax", -67.9, 46.0, -67.5, 46.4, "Houlton area (map, pale)")
# Disputed strips: in v3 but not v2 on sheets where v2 looked correct.
v2 = json.load(open("/repo/data/v2-dataregions.json"))
v3 = json.load(open("/repo/data/conus/dataregions.json"))
def bbox(polys):
    xs = [p[0] for poly in polys for p in poly]; ys = [p[1] for poly in polys for p in poly]
    return min(xs), min(ys), max(xs), max(ys)
for chart in ("Chicago", "Dallas-Ft_Worth", "San_Antonio", "Denver", "New_York"):
    b2, b3 = bbox(v2[chart]), bbox(v3[chart])
    print(f"{chart:20} v2 bbox {tuple(round(v,2) for v in b2)}  v3 bbox {tuple(round(v,2) for v in b3)}")
