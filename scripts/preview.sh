#!/bin/bash
# Region mosaic preview for cutline QA: low-res cutline-cropped warps of
# every unit, mosaicked into ONE jpeg. Minutes, not hours — judge panel
# bleed, furniture and coverage holes without baking a tile.
#
# DRAW ORDER IS LOAD-BEARING: every sheet's OVEREDGE strips are laid
# down first, then every sheet's BODY on top. A sheet's printed neatline
# stroke sits on its overedge edge, so wherever a neighbour has clean
# map over the same ground the body covers the stroke and the joint is
# seamless. Leaving it to alphabetical order is what left a black line
# across 44N by Matinicus.
#
# REGION selects the chart list (default conus); PREVIEW_RES overrides
# meters/px (default = the z7 tile grid).
set -euo pipefail
REGION="${REGION:-conus}"
RES="${PREVIEW_RES:-407.664150854}"
mkdir -p "/repo/data/$REGION"
cd "/repo/data/$REGION"
rm -rf preview && mkdir -p preview
python3 /repo/scripts/units.py "$REGION" > units.tsv
xargs -P 4 -a units.tsv -d '\n' -I{} bash -c '
  set -e
  IFS=$(printf "\t") read -r uid tif vrt cut <<< "{}"
  [ -f "$vrt" ] || gdal_translate -q -of vrt -expand rgb "$tif" "$vrt"
  side="${cut%.cutline.geojson}.side.geojson"
  if [ -f "$side" ]; then
    timeout "${WARP_TIMEOUT:-600}" gdalwarp -q -t_srs EPSG:3857 -tr "'"$RES"'" "'"$RES"'" \
      -r average -dstalpha -cutline "$side" -crop_to_cutline "$vrt" "preview/1side_$uid.tif"
  fi
  timeout "${WARP_TIMEOUT:-600}" gdalwarp -q -t_srs EPSG:3857 -tr "'"$RES"'" "'"$RES"'" \
    -r average -dstalpha -cutline "$cut" -crop_to_cutline "$vrt" "preview/2body_$uid.tif"
'
# sides first, bodies last: later files win in a VRT
gdalbuildvrt -q preview/conus.vrt preview/1side_*.tif preview/2body_*.tif 2>/dev/null \
  || gdalbuildvrt -q preview/conus.vrt preview/2body_*.tif
gdal_translate -q -of JPEG -co QUALITY=88 -b 1 -b 2 -b 3 preview/conus.vrt preview/conus.jpg
echo "wrote $(gdalinfo preview/conus.jpg | grep "Size is")"
