"""Print shell assignments for one unit: UNIT, TIF, VRT, CUT.

Usage:  eval "$(python3 scripts/unit-env.py conus Chicago)"

Keeps the workflow free of inline path logic — units.py stays the single
place that knows how a chart-list entry maps to files.
"""

import shlex
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import units  # noqa: E402

region, entry = sys.argv[1], sys.argv[2]
tif, vrt, cut = units.unit_paths(entry, region)
# NOT "UID": that is a readonly builtin in bash and the assignment
# fails the step ("UID: readonly variable").
print(f"UNIT={shlex.quote(units.unit_id(entry))}")
print(f"TIF={shlex.quote(tif)}")
print(f"VRT={shlex.quote(vrt)}")
print(f"CUT={shlex.quote(cut)}")
