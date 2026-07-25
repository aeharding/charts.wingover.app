#!/bin/bash
# Fetch one sheet's zip from FAA into data/conus/src/<Chart>/.
# Usage: ci-fetch.sh <Chart> <cycle MM-DD-YYYY>
set -euo pipefail
chart="$1"
cycle="$2"
mkdir -p "data/conus/src/$chart"
python3 - "$chart" "$cycle" <<'EOF'
import io
import sys
import urllib.request
import zipfile

chart, cycle = sys.argv[1], sys.argv[2]
url = f"https://aeronav.faa.gov/visual/{cycle}/sectional-files/{chart}.zip"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
data = urllib.request.urlopen(req, timeout=180).read()
zipfile.ZipFile(io.BytesIO(data)).extractall(f"data/conus/src/{chart}")
print(f"fetched {chart}: {len(data) >> 20} MB")
EOF
