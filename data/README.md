# data/

Runtime cache and output directory.

- `data/cache/` — downloaded DEM tiles and OSM extracts. Content-addressed by `(provider, version, tile_id)`. **Never** commit anything here.
- `data/output/` — generated map bundles. **Never** commit anything here either.

Both are gitignored. Committed test fixtures live under `tests/fixtures/`.
