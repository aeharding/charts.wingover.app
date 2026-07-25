#!/bin/bash
# v3 bake: detected-cutline warps (ink-aware classifier, see derive.py),
# one CONUS mosaic, @3x d4 JPEG XL pyramid z0-12.
# Runs inside ghcr.io/osgeo/gdal:ubuntu-full-latest with the repo mounted
# at /repo — see README.md. Idempotent: finished warps are kept, so a
# crashed run resumes where it stopped.
set -euo pipefail
cd /repo/data/conus
CHARTS=$(grep -vE '^\s*(#|$)' /repo/charts.txt)

# Every listed chart must have a cutline (finalize.py output) BEFORE any
# work starts — a stale or missing cutline must never silently warp old
# geometry (the v2 lesson).
for c in $CHARTS; do
  [ -f "src/$c/cutline2.geojson" ] || { echo "MISSING cutline2: $c" >&2; exit 1; }
done

# Warp at the @3x z12 ground resolution (40075016.686 / (4096 * 768)):
# one resample from the source LCC scan straight to the finest tile grid.
mkdir -p warped
echo "$CHARTS" | xargs -P 4 -I{} bash -c '
  set -e
  c="{}"
  out="warped/$c.tif"
  [ -f "$out" ] && exit 0
  tif=$(ls "src/$c"/*.tif | head -1)
  gdal_translate -q -of vrt -expand rgb "$tif" "src/$c/rgb.vrt"
  gdalwarp -q -t_srs EPSG:3857 \
    -tr 12.7395047141960 12.7395047141960 \
    -r cubic -dstalpha -cutline "src/$c/cutline2.geojson" -crop_to_cutline \
    -co COMPRESS=DEFLATE -co TILED=YES -co BIGTIFF=IF_SAFER \
    -multi -wo NUM_THREADS=3 "src/$c/rgb.vrt" "$out.tmp.tif"
  mv "$out.tmp.tif" "$out"
  echo "warped $c"
'

# Loud completeness check — v2 lost whole sheets to silent warp failures.
n_expected=$(echo "$CHARTS" | wc -l)
n_actual=$(ls warped/*.tif | wc -l)
[ "$n_expected" = "$n_actual" ] || { echo "warp incomplete: $n_actual/$n_expected" >&2; exit 1; }

gdalbuildvrt -overwrite conus.vrt warped/*.tif
gdal raster tile -f JPEGXL \
  --creation-option LOSSLESS=NO --creation-option DISTANCE=4 --creation-option EFFORT=7 \
  --tile-size 768 --min-zoom 0 --max-zoom 12 --convention xyz \
  --resampling cubic --overview-resampling average \
  --skip-blank --webviewer none --progress \
  conus.vrt tiles3x
echo "total: $(find tiles3x -name '*.jxl' | wc -l) tiles, $(du -sh tiles3x | cut -f1)"
