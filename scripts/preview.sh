#!/bin/bash
# Region mosaic preview for cutline QA: low-res cutline-cropped warps of
# every unit, mosaicked into ONE jpeg. Minutes, not hours — judge panel
# bleed, furniture and coverage holes without baking a tile.
# REGION selects the chart list (default conus); PREVIEW_RES overrides
# meters/px (default = the z7 tile grid).
set -euo pipefail
REGION="${REGION:-conus}"
RES="${PREVIEW_RES:-407.664150854}"
mkdir -p "/repo/data/$REGION"
cd "/repo/data/$REGION"
rm -rf preview && mkdir -p preview
python3 /repo/scripts/units.py "$REGION" | while IFS=$'\t' read -r uid tif vrt cut; do
  printf '%s\t%s\t%s\t%s\n' "$uid" "$tif" "$vrt" "$cut"
done > units.tsv
xargs -P 4 -a units.tsv -d '\n' -I{} bash -c '
  set -e
  IFS=$(printf "\t") read -r uid tif vrt cut <<< "{}"
  [ -f "$vrt" ] || gdal_translate -q -of vrt -expand rgb "$tif" "$vrt"
  timeout "${WARP_TIMEOUT:-600}" gdalwarp -q -t_srs EPSG:3857 -tr "'"$RES"'" "'"$RES"'" -r average -dstalpha \
    -cutline "$cut" -crop_to_cutline "$vrt" "preview/$uid.tif"
'
gdalbuildvrt -q preview/conus.vrt preview/*.tif
gdal_translate -q -of JPEG -co QUALITY=88 -b 1 -b 2 -b 3 preview/conus.vrt preview/conus.jpg
echo "wrote $(gdalinfo preview/conus.jpg | grep "Size is")"
