#!/bin/bash
# Sum the tiles a bake run actually produced, per band.
#
# `gh run view --log` does NOT include the logs of called workflows, so
# for a bake-all run it returns nothing and looks like zero tiles. The
# counts have to be read per job through the API.
#
# Job status is not evidence: two bakes have reported success while
# shipping almost nothing. This reads what each band really built.
#
# Usage: bash scripts/run-tile-counts.sh <run-id>
set -euo pipefail
RUN="${1:?usage: run-tile-counts.sh <run-id>}"
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)

gh run view "$RUN" --json jobs \
  --jq '.jobs[] | select(.name | test("tile|overview")) | "\(.databaseId)"' \
| while read -r jid; do
    gh api "repos/$REPO/actions/jobs/$jid/logs" 2>/dev/null \
      | grep -oE "(band [a-zA-Z0-9-]+|overview): [0-9]+ tiles" || true
  done \
| sed -E 's/.*(band [a-zA-Z0-9-]+|overview): ([0-9]+) tiles/\1 \2/' \
| sort -u \
| awk '{n[$1]=$NF} END {
    t=0; for (b in n) { printf "  %-12s %8d\n", b, n[b]; t+=n[b] }
    printf "  %-12s %8d\n", "TOTAL", t
  }' \
| sort
