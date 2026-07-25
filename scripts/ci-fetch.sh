#!/bin/bash
# Ensure one sheet's source is present in data/conus/src/<Chart>/.
# Zips live in data/zips/ (cycle-immutable, cached across CI runs by
# actions/cache); FAA is contacted only when the zip is absent — with
# the fetch job seeding the cache, that is once per cycle ever.
# Usage: ci-fetch.sh <Chart> <cycle MM-DD-YYYY>
set -euo pipefail
chart="$1"
cycle="$2"
mkdir -p data/zips "data/conus/src/$chart"
python3 - "$chart" "$cycle" <<'EOF'
import os
import sys
import urllib.request
import zipfile

chart, cycle = sys.argv[1], sys.argv[2]
zip_path = f"data/zips/{chart}.zip"
if not os.path.exists(zip_path):
    url = f"https://aeronav.faa.gov/visual/{cycle}/sectional-files/{chart}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=180).read()
    with open(zip_path + ".part", "wb") as f:
        f.write(data)
    os.rename(zip_path + ".part", zip_path)
    print(f"fetched {chart}: {len(data) >> 20} MB")
else:
    print(f"cached {chart}")
zipfile.ZipFile(zip_path).extractall(f"data/conus/src/{chart}")
EOF
