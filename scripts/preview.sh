#!/bin/bash
# Whole-CONUS mosaic preview for cutline QA: low-res cutline-cropped
# warps of every sheet, mosaicked into ONE jpeg. Minutes, not hours —
# judge panel/collar bleed and coverage holes without baking a tile.
# PREVIEW_RES overrides meters/px (default = the z7 tile grid).
set -euo pipefail
cd /repo/data/conus
CHARTS=$(grep -vE '^\s*(#|$)' /repo/charts.txt)
RES="${PREVIEW_RES:-407.664150854}"
rm -rf preview && mkdir -p preview
echo "$CHARTS" | xargs -P 4 -I{} bash -c '
  set -e
  c="{}"
  [ -f "src/$c/rgb.vrt" ] || gdal_translate -q -of vrt -expand rgb "$(ls "src/$c"/*.tif | head -1)" "src/$c/rgb.vrt"
  gdalwarp -q -t_srs EPSG:3857 -tr "'"$RES"'" "'"$RES"'" -r average -dstalpha \
    -cutline "src/$c/cutline2.geojson" -crop_to_cutline \
    "src/$c/rgb.vrt" "preview/$c.tif"
'
gdalbuildvrt -q preview/conus.vrt preview/*.tif
gdal_translate -q -of JPEG -co QUALITY=88 -b 1 -b 2 -b 3 preview/conus.vrt preview/conus.jpg
echo "wrote $(gdalinfo preview/conus.jpg | grep "Size is")"
