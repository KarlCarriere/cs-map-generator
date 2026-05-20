# Test Fixtures

This directory is reserved for test fixtures committed to the repository.

The current MVP test suite generates synthetic SRTM tiles at fixture-setup time via
`tests/conftest.py` (`srtm_cache_directory` fixture). This keeps the repository small (real SRTM
tiles are ~26 MB each) and reproducible across machines without requiring the test author to
hand-place binary fixtures.

## Files

- `tiny_bbox.json` — bbox metadata used by every offline test. Centred at (0.5°, 0.5°) so a
  single synthetic SRTM tile (N00E000) covers it.
- `water/tiny_water.json` — small offline water fixture for the v0.2 golden-output test.
  Hand-crafted polygon + waterway (no coastlines — those have their own pure-shapely test
  suite in `tests/infrastructure/test_coastline_reconstruction.py`). Provenance is the file
  header itself; the geometry is NOT scraped from a live OSM extract.

## Provenance Discipline

If/when a real OSM extract is committed as a fixture (a vendored .osm.pbf slice for a known
bbox), it must include:

1. The bbox it was extracted from (W,S,E,N + CRS EPSG).
2. The OSM data timestamp (the `osmosis_replication_timestamp` or equivalent).
3. The extraction command line used (`osmium extract --bbox=...`).
4. An attribution note (© OpenStreetMap contributors, ODbL).

No live Overpass or Geofabrik download is permitted at test time. The pytest conftest does not
install a global socket-blocker (which interferes with pytest internals), but every test path
must either inject a fake or read from a committed file under this directory.
