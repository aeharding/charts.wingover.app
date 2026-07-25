# charts.wingover.app

Tile factory for Wingover's self-hosted FAA VFR sectional charts:
JPEG XL rasters on Cloudflare R2, served at https://charts.wingover.app.

## Pipeline

Everything runs inside `ghcr.io/osgeo/gdal:ubuntu-full-latest` with this
repo mounted at `/repo`. Sources and outputs live under `data/`
(gitignored).

1. **Fetch** — download every sheet in `charts.txt` for the current
   cycle into `data/conus/src/<Chart>/`:
   `https://aeronav.faa.gov/visual/<MM-DD-YYYY>/sectional-files/<Chart>.zip`
   (cycle discovery: FAA APRA,
   `external-api.faa.gov/apra/vfr/sectional/chart?edition=current`).
2. **Derive** — `scripts/derive.py`: detect each sheet's map-data region
   (vs legend panels / collar) on a 5-minute cell grid. A cell is map
   data if it is opaque and (not white-dominant OR carries saturated
   chart ink). Largest connected component, 1-cell opening, per-column
   full spans.
3. **Finalize** — `scripts/finalize.py`: rolling-median smoothing,
   axis-enclosure hole gate (must be verified blank-on-sheet), densified
   MultiPolygon cutlines written to `src/<Chart>/cutline2.geojson`.
4. **Bake** — `scripts/bake.sh`: cutline-cropped warp of every sheet to
   EPSG:3857 at the @3x z12 grid resolution, one CONUS VRT, then a
   z0-12 xyz pyramid of 768px JPEG XL tiles (distance 4, effort 7).
5. **Ship** — `aws s3 sync` to R2 under a NEW immutable prefix
   `/vfr/<cycle><rev>/3x/{z}/{x}/{y}.jxl` (never rewrite an existing
   prefix: tiles are cached immutable at the edge and in clients), then
   point the app at it. Keep S3 concurrency ≤ 24 (R2 throttles above).

## Hard-won invariants

- The chart list is explicit (`charts.txt`); nothing is discovered from
  the filesystem. A listed sheet that is missing fails the run.
- Every bake gets a fresh prefix; `latest.json` is the only mutable key.
- Warp completeness is asserted before mosaicking — a silently failed
  warp once shipped as a missing sheet.
- Cutlines are detected, never nominal quadrangles: sheets print legend
  panels inside the georeferenced bbox and neighbors carry the real
  imagery as overlap.
- Sheet edges are fractional (44°30' northern tier, stepped corners);
  cutline polygons are densified 0.05° because gdalwarp rasterizes them
  with straight chords in source LCC space.
