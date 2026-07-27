"""Verify the tile job's path construction matches what warp uploads.

The tile stage was the one step the earlier dry-run skipped, and it is
exactly where the last dispatch died: warp uploads "$UNIT.tif" while
tile built paths from raw chart lines, so every multi-scan sheet 404'd.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import units

bad = 0
for region in ("conus", "alaska", "hawaii", "mariana", "samoa",
               "aleutians_west", "aleutians_far", "caribbean"):
    for entry in units.read_list(region):
        uid = units.unit_id(entry)
        # what warp uploads (unit-env.py UNIT) vs what tile now asks for
        if " " in uid or ":" in uid:
            print(f"UNSAFE uid for S3 key: {region} {entry!r} -> {uid!r}")
            bad += 1
        tif, vrt, cut = units.unit_paths(entry)
        if not os.path.basename(vrt).startswith(uid):
            print(f"MISMATCH {region} {entry!r}: vrt {os.path.basename(vrt)} vs uid {uid}")
            bad += 1
print("units checked; problems:", bad)
sys.exit(1 if bad else 0)
