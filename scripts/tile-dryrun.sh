#!/bin/bash
# Local warp+tile dry run: the stages CI's dry run also covers, but
# runnable in minutes on a laptop instead of a dispatch.
#
# Every bake failure of the last week lived PAST the gates, because the
# local checks stopped at the cutlines. This runs the real warp (body AND
# overedge), the real band selection (scripts/bandsel.py, shared with the
# workflow) and the real tiler, and fails if a band produces no tiles.
#
# REGIONS is the space-separated list to prepare; BANDS_FOR picks whose
# bands to tile ("all" for the global set, which is what the bake uses).
# Tiling one region alone is fine for a quick check, but only "all"
# reproduces what ships, because CI tiles every region in one pass.
#
# Usage:
#   REGIONS=samoa BANDS_FOR=samoa bash scripts/tile-dryrun.sh
#   REGIONS="conus caribbean" BANDS_FOR=all bash scripts/tile-dryrun.sh
set -euo pipefail
REGIONS="${REGIONS:-${REGION:-samoa}}"
BANDS_FOR="${BANDS_FOR:-${REGION:-samoa}}"
OUT=/repo/data/dryrun
rm -rf "$OUT" && mkdir -p "$OUT/warped"
cd "$OUT"

for region in $REGIONS; do
  python3 /repo/scripts/units.py "$region" > "units_$region.tsv"
  mkdir -p "warped/$region"
  while IFS=$'\t' read -r uid tif vrt cut; do
    [ -f "$vrt" ] || gdal_translate -q -of vrt -expand rgb "$tif" "$vrt"
    echo "warping $region/$uid"
    timeout "${WARP_TIMEOUT:-1800}" gdalwarp -q -t_srs EPSG:3857 \
      -tr 12.7395047141960 12.7395047141960 \
      -r cubic -dstalpha -cutline "$cut" -crop_to_cutline \
      -co COMPRESS=DEFLATE -co TILED=YES -co BIGTIFF=IF_SAFER \
      -multi -wo NUM_THREADS=3 "$vrt" "warped/$region/$uid.tif"
    # Overedge strip too. The bake stages it now; without it the local
    # picture would be built from different inputs than the shipped
    # tiles, which is exactly how the seams I signed off on were checked
    # against a mosaic the bake could not produce.
    side="${cut%.cutline.geojson}.side.geojson"
    if [ -f "$side" ]; then
      timeout "${WARP_TIMEOUT:-1800}" gdalwarp -q -t_srs EPSG:3857 \
        -tr 12.7395047141960 12.7395047141960 \
        -r cubic -dstalpha -cutline "$side" -crop_to_cutline \
        -co COMPRESS=DEFLATE -co TILED=YES -co BIGTIFF=IF_SAFER \
        -multi -wo NUM_THREADS=3 "$vrt" "warped/$region/$uid.side.tif"
    fi
  done < "units_$region.tsv"
done

python3 /repo/scripts/bands.py "$BANDS_FOR" \
  | python3 -c 'import json,sys
for b in json.load(sys.stdin):
    print(b["name"], b["x0"], b["x1"])' > bands.txt
nbands=$(wc -l < bands.txt)
echo "$BANDS_FOR: $nbands bands"
[ "$nbands" -gt 0 ] || { echo "ZERO bands" >&2; exit 1; }

total=0
tiled=0
while read -r name x0 x1; do
  if ! python3 /repo/scripts/bandsel.py "$BANDS_FOR" "$x0" "$x1" \
       'warped/{region}/{uid}{suffix}.tif' 2>/dev/null; then
    echo "band $name: no sheets, skipping"
    continue
  fi
  . ./bandy.env
  # DRAW ORDER from fetch.txt: overedge first, then bodies, by priority.
  : > order.txt
  while IFS=$'\t' read -r region uid suffix; do
    [ -n "$uid" ] || continue
    f="warped/$region/$uid$suffix.tif"
    [ -f "$f" ] && echo "$f" >> order.txt
  done < fetch.txt
  if [ ! -s order.txt ]; then
    echo "band $name: no rasters present, skipping"
    continue
  fi
  rm -rf tiles3x
  gdalbuildvrt -q -te "$x0" "$BY0" "$x1" "$BY1" -input_file_list order.txt band.vrt
  timeout "${TILE_TIMEOUT:-3600}" gdal raster tile -f JPEGXL \
    --creation-option LOSSLESS=NO --creation-option DISTANCE=4 --creation-option EFFORT=7 \
    --tile-size 768 --min-zoom 8 --max-zoom 12 --convention xyz \
    --resampling cubic --overview-resampling average \
    --skip-blank --webviewer none band.vrt tiles3x
  n=$(find tiles3x -name '*.jxl' | wc -l)
  echo "band $name: $n tiles from $(wc -l < order.txt) rasters"
  [ "$n" -gt 0 ] || { echo "band $name produced ZERO tiles" >&2; exit 1; }
  total=$((total + n))
  tiled=$((tiled + 1))
done < bands.txt
[ "$total" -gt 0 ] || { echo "ZERO tiles overall" >&2; exit 1; }
echo "TILE DRY RUN OK ($REGIONS): $total tiles across $tiled of $nbands bands"
