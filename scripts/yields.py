"""Cross-region precedence: which region wins where two chart the same ground.

Shared by make-yield.py (writes the polygon) and finalize.py (applies it
and refuses a stale one), so the staleness rule has exactly one
definition.
"""

import hashlib
import json
import os

REPO = os.environ.get("REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


def outranked_by(region):
    """Regions that beat this one where they overlap."""
    cfg = json.load(open(f"{REPO}/regions.json"))
    return list(cfg.get(region, {}).get("yields_to", []))


def lists_sha(regions):
    """Fingerprint of the outranking regions' chart lists.

    Keyed to the SHEET SET, not the cycle: a sheet's neatline is printed
    on the sheet, so the coverage polygon moves when FAA adds, retires or
    renames a sheet, not every 56 days. That keeps the staleness check
    from crying wolf on every cycle while still catching the change that
    actually invalidates the geometry.
    """
    h = hashlib.sha256()
    for region in sorted(regions):
        with open(f"{REPO}/charts-{region}.txt") as f:
            entries = sorted(
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            )
        h.update(region.encode() + b"\0" + "\n".join(entries).encode() + b"\0")
    return h.hexdigest()


def load(region):
    """(geometry, path) this region must not claim, or (None, None).

    Raises if the committed polygon no longer matches the sheet set it
    was built from - shipping a stale yield would either re-open the
    overlap or carve a gap, and both are invisible until a pilot finds
    them.
    """
    path = f"{REPO}/yields/{region}.geojson"
    outranking = outranked_by(region)
    if not outranking:
        return None, None
    if not os.path.exists(path):
        raise SystemExit(
            f"{region} yields to {outranking} but {path} is missing; "
            f"run scripts/make-yield.py {region}"
        )
    doc = json.load(open(path))
    want = lists_sha(outranking)
    if doc.get("lists_sha") != want:
        raise SystemExit(
            f"{path} is STALE: built from a different sheet set for "
            f"{outranking}. Re-derive those regions and rerun "
            f"scripts/make-yield.py {region}"
        )
    from osgeo import ogr

    return (
        ogr.CreateGeometryFromJson(json.dumps(doc["features"][0]["geometry"])),
        path,
    )
