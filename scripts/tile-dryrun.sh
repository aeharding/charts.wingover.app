#!/bin/bash
# Local warp+tile dry run for ONE region: the stage CI's dry run also
# covers, but runnable in minutes on a laptop instead of a dispatch.
#
# Every bake failure of the last week lived PAST the gates, because the
# local checks stopped at the cutlines. This runs the real warp, the
# real band selection (scripts/bandsel.py, shared with the workflow) and
# the real tiler, and fails if any band produces zero tiles.
#
# Usage: REGION=samoa bash scripts/tile-dryrun.sh
set -euo pipefail
REGION="${REGION:-samoa}"
cd "/repo/data/$REGION"
rm -rf dryrun && mkdir -p dryrun/warped
cd dryrun

python3 /repo/scripts/units.py "$REGION" > units.tsv
while IFS=$'\t' read -r uid tif vrt cut; do
  [ -f "$vrt" ] || gdal_translate -q -of vrt -expand rgb "$tif" "$vrt"
  echo "warping $uid"
  timeout "${WARP_TIMEOUT:-1800}" gdalwarp -q -t_srs EPSG:3857 \
    -tr 12.7395047141960 12.7395047141960 \
    -r cubic -dstalpha -cutline "$cut" -crop_to_cutline \
    -co COMPRESS=DEFLATE -co TILED=YES -co BIGTIFF=IF_SAFER \
    -multi -wo NUM_THREADS=3 "$vrt" "warped/$uid.tif"
done < units.tsv

python3 /repo/scripts/bands.py "$REGION" \
  | python3 -c 'import json,sys
for b in json.load(sys.stdin):
    print(b["name"], b["x0"], b["x1"])' > bands.txt
nbands=$(wc -l < bands.txt)
echo "$REGION: $nbands bands"
[ "$nbands" -gt 0 ] || { echo "region produced ZERO bands" >&2; exit 1; }

total=0
while read -r name x0 x1; do
  python3 /repo/scripts/bandsel.py "$REGION" "$x0" "$x1" 'warped/{uid}.tif'
  . ./bandy.env
  rm -rf tiles3x
  gdalbuildvrt -q -te "$x0" "$BY0" "$x1" "$BY1" band.vrt $(sed 's|^|warped/|; s|$|.tif|' fetch.txt)
  timeout "${TILE_TIMEOUT:-3600}" gdal raster tile -f JPEGXL \
    --creation-option LOSSLESS=NO --creation-option DISTANCE=4 --creation-option EFFORT=7 \
    --tile-size 768 --min-zoom 8 --max-zoom 12 --convention xyz \
    --resampling cubic --overview-resampling average \
    --skip-blank --webviewer none band.vrt tiles3x
  n=$(find tiles3x -name '*.jxl' | wc -l)
  echo "band $name: $n tiles"
  [ "$n" -gt 0 ] || { echo "band $name produced ZERO tiles" >&2; exit 1; }
  total=$((total + n))
done < bands.txt
[ "$total" -gt 0 ] || { echo "ZERO tiles overall" >&2; exit 1; }
echo "TILE DRY RUN OK ($REGION): $total tiles across $nbands bands"
