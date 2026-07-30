"""Maintain vfr/latest.json - the app's one source of truth for tiles.

The app never builds prefix URLs itself: prefixes are immutable-cached
release directories with letter suffixes (07-09-2026k), and old ones are
deleted by a 180-day bucket lifecycle rule. latest.json is the mutable
pointer in front of them (short TTL, never immutable).

Shape:
  {"current": {cycle, tiles, minZoom, maxZoom, effective, baked},
   "next": <same shape> | null}

A cycle's files appear ~20 days before they take force, and the bake
runs as soon as they appear, so a fresh bake lands as "next" until its
effective moment (0901Z on the FAA effective date). Clients pick next
when now >= next.effective; the promote invocation also rotates it
server-side so a client that only reads "current" is at most stale,
never premature.

Usage:
  publish-manifest.py publish <cycle MM-DD-YYYY> <prefix>   # after verify
  publish-manifest.py promote                               # cron, idempotent
Env: BUCKET, R2_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
"""

import datetime
import json
import subprocess
import sys
import os

BUCKET = os.environ["BUCKET"]
ENDPOINT = os.environ["R2_ENDPOINT"]
KEY = f"s3://{BUCKET}/vfr/latest.json"


def aws(*args, **kw):
    return subprocess.run(
        ["aws", "--endpoint-url", ENDPOINT, *args],
        capture_output=True, text=True, **kw,
    )


def read():
    r = aws("s3", "cp", KEY, "-")
    if r.returncode != 0:
        return {"current": None, "next": None}
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        return {"current": None, "next": None}
    # tolerate the pre-manifest v1 file, which had a different shape
    if "current" not in doc:
        return {"current": None, "next": None}
    return {"current": doc.get("current"), "next": doc.get("next")}


def write(doc):
    p = "/tmp/latest.json"
    json.dump(doc, open(p, "w"), indent=1)
    r = aws(
        "s3", "cp", p, KEY,
        "--content-type", "application/json",
        # SHORT TTL: this is the one mutable object in the product.
        "--cache-control", "public, max-age=300",
    )
    if r.returncode != 0:
        raise SystemExit(f"upload failed: {r.stderr}")
    print(json.dumps(doc, indent=1))


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def entry(cycle_mmddyyyy, prefix):
    m, d, y = cycle_mmddyyyy.split("-")
    iso = f"{y}-{m}-{d}"
    return {
        "cycle": iso,
        "prefix": f"vfr/{prefix}",
        "tiles": (
            "https://charts.wingover.app/vfr/" + prefix + "/3x/{z}/{x}/{y}.jxl"
        ),
        "minZoom": 0,
        "maxZoom": 12,
        # FAA charts take force at 0901Z on the effective date.
        "effective": f"{iso}T09:01:00Z",
        "baked": now_iso(),
    }


def promote(doc):
    nxt = doc.get("next")
    if nxt and nxt["effective"] <= now_iso():
        doc["current"] = nxt
        doc["next"] = None
        print(f"promoted {nxt['cycle']} to current")
    return doc


def main(argv):
    doc = read()
    if argv[0] == "publish":
        e = entry(argv[1], argv[2])
        if e["effective"] <= now_iso():
            # already in force (first bake, or a re-bake of the current
            # cycle): straight to current
            doc["current"] = e
            if doc.get("next") and doc["next"]["cycle"] <= e["cycle"]:
                doc["next"] = None
        else:
            doc["next"] = e
    elif argv[0] != "promote":
        raise SystemExit(__doc__)
    write(promote(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
