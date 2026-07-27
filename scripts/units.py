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

# Repo root resolved from THIS FILE, never hardcoded: the CI plan job
# runs outside the container where /repo does not exist. bands.py
# failing there produced an EMPTY tile matrix, so every tile job
# skipped silently and the bake shipped only z0-7.
REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


import os


SRC = f"{REPO}/data/src"


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
        dpath = os.path.join(SRC, d)
        tifs = (
            [f for f in os.listdir(dpath) if f.lower().endswith(".tif")]
            if os.path.isdir(dpath)
            else []
        )
        if len(tifs) > 1:
            raise SystemExit(
                f"{d} has {len(tifs)} TIFs; list its units explicitly as "
                f"'{d}::<stem>' in the region chart list"
            )
        # No scan present is fine: the cutlines stage works purely on
        # geometry and never reads a TIF, so path derivation must not
        # demand one (it failed the whole bake at that stage).
        tif = os.path.join(dpath, tifs[0] if tifs else d + ".tif")
    uid = unit_id(entry)
    return tif, os.path.join(SRC, d, uid + ".vrt"), os.path.join(SRC, d, uid + ".cutline.geojson")


def read_list(region):
    return [
        line.strip()
        for line in open(f"{REPO}/charts-{region}.txt")
        if line.strip() and not line.startswith("#")
    ]


if __name__ == "__main__":
    import sys

    for entry in read_list(sys.argv[1]):
        tif, vrt, cut = unit_paths(entry)
        print("\t".join((unit_id(entry), tif, vrt, cut)))
