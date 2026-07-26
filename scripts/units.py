"""Sheet UNITS: one georeferenced scan each.

Most FAA sheets are one TIF, but some ship several separately
georeferenced files in one zip — the Hawaiian Islands sheet carries the
main chart plus Honolulu, Mariana and Samoan Islands insets, and Western
Aleutian Islands is split East/West precisely because it straddles the
antimeridian. Each file is its own tiling unit: no chopping needed for
those insets (they are already separate rasters), and the Aleutians
split means neither half crosses the antimeridian, so both tile in
web mercator without special handling.

A chart list entry is either "Dir" (a single-TIF sheet) or
"Dir::Tif Stem" for one file of a multi-file sheet.
"""

import os

SRC = "/repo/data/src"


def unit_id(entry):
    """Filename-safe id for a unit entry."""
    if "::" not in entry:
        return entry
    d, stem = entry.split("::", 1)
    return d + "__" + stem.replace(" ", "_")


def unit_paths(entry):
    """(tif, vrt, cutline) absolute paths for a chart-list entry."""
    if "::" in entry:
        d, stem = entry.split("::", 1)
        tif = os.path.join(SRC, d, stem + ".tif")
    else:
        d = entry
        tifs = [f for f in os.listdir(os.path.join(SRC, d)) if f.lower().endswith(".tif")]
        if len(tifs) != 1:
            raise SystemExit(
                f"{d} has {len(tifs)} TIFs; list its units explicitly as "
                f"'{d}::<stem>' in the region chart list"
            )
        tif = os.path.join(SRC, d, tifs[0])
    uid = unit_id(entry)
    return tif, os.path.join(SRC, d, uid + ".vrt"), os.path.join(SRC, d, uid + ".cutline.geojson")


def read_list(region):
    return [
        line.strip()
        for line in open(f"/repo/charts-{region}.txt")
        if line.strip() and not line.startswith("#")
    ]


if __name__ == "__main__":
    import sys

    for entry in read_list(sys.argv[1]):
        tif, vrt, cut = unit_paths(entry)
        print("\t".join((unit_id(entry), tif, vrt, cut)))
