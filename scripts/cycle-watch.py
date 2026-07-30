"""Decide whether a new FAA cycle needs baking. Decision only - the
workflow does the dispatching, so this is testable without side effects.

FAA publishes VFR charts on a fixed 56-day cadence (anchor: 2026-07-09)
and uploads each cycle's files ~20 days before they take force. Baking
the moment files appear gives a ~3-week audit window before pilots see
the new cycle: every sheet republishes every cycle, so neatlines and
furniture can move, and the gates need time to be wrong in.

A cycle needs baking when:
  - its files exist on aeronav (BOTH listings: sectional-files AND
    Caribbean - they publish separately and fetch needs both), and
  - latest.json knows nothing about it (neither current nor next).

Re-bakes of a known cycle are deliberate human actions, never cron's.

Output (GITHUB_OUTPUT if set, else stdout): cycle=MM-DD-YYYY or nothing.
"""

import datetime
import json
import os
import re
import sys
import urllib.request

ANCHOR = datetime.date(2026, 7, 9)
CADENCE = datetime.timedelta(days=56)
MANIFEST = "https://charts.wingover.app/vfr/latest.json"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60).read().decode("latin-1")


def listing_has_zips(cycle_mmddyyyy, path):
    try:
        html = fetch(f"https://aeronav.faa.gov/visual/{cycle_mmddyyyy}/{path}/")
    except Exception:
        return 0
    return len(re.findall(r'HREF="[^"]+\.zip"', html, re.I))


def known_cycles():
    try:
        doc = json.loads(fetch(MANIFEST))
    except Exception:
        return set()
    out = set()
    for k in ("current", "next"):
        if isinstance(doc.get(k), dict) and doc[k].get("cycle"):
            out.add(doc[k]["cycle"])
    return out


def main():
    today = datetime.date.today()
    known = known_cycles()
    print(f"manifest knows: {sorted(known) or 'nothing'}", file=sys.stderr)

    # Candidates: the in-force cycle and the one after it. NEVER k0-1:
    # a superseded cycle's files stay on aeronav for a while, and cron
    # must not bake the past.
    k0 = (today - ANCHOR) // CADENCE
    for k in (k0, k0 + 1):
        eff = ANCHOR + CADENCE * k
        if eff.isoformat() in known:
            continue
        mmdd = eff.strftime("%m-%d-%Y")
        sec = listing_has_zips(mmdd, "sectional-files")
        car = listing_has_zips(mmdd, "Caribbean")
        print(f"cycle {mmdd}: {sec} sectional zips, {car} caribbean zips",
              file=sys.stderr)
        # a full cycle publishes ~53 sectionals and 2 Caribbean; require
        # most of both so a half-uploaded cycle does not trigger a bake
        # that then fails fetch on the missing sheets
        if sec >= 40 and car >= 2:
            out = os.environ.get("GITHUB_OUTPUT")
            line = f"cycle={mmdd}"
            if out:
                with open(out, "a") as f:
                    f.write(line + "\n")
            print(line)
            return 0
    print("nothing to bake", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
