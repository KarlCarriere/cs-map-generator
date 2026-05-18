# cs2_map_generator

A deterministic GIS compiler that converts a real-world bounding box into engine-ready map artifacts for **Cities: Skylines 1** and **Cities: Skylines II**. Same inputs + same seed = byte-identical heightmaps and overlays.

## Quickstart

The supported development environment is the Dev Container. GDAL on the host is not required, not tested, and not supported.

1. Open this folder in VS Code with the Dev Containers extension. The container builds on first open.
2. Inside the container, sync dependencies:
   ```bash
   uv sync --all-extras --all-groups
   ```
3. Run the test suite:
   ```bash
   uv run pytest
   ```
4. Generate a CS1 map centred on a coordinate (cached DEM tiles will be fetched on first run; subsequent runs are offline):
   ```bash
   uv run cs-mapgen generate \
     --center 46.81,-71.21 \
     --target cs1 \
     --out data/output/quebec \
     --seed 42
   ```
   `--center` takes `LAT,LON` (latitude first, the human-natural order). The map is centred on that coordinate and extends 4 tiles in every cardinal direction for CS1 (10 for CS2) by default; override with `--radius-tiles N`. The legacy `--bbox west,south,east,north` flag (lon-first, matching W/S/E/N) is still supported for scripting workflows.

5. Or run the API:
   ```bash
   uv run uvicorn cs_mapgen.interfaces.http.app:app --reload
   curl -X POST http://localhost:8000/maps \
     -H "Content-Type: application/json" \
     -d '{"input":{"kind":"center","lat":46.81,"lon":-71.21},"target":"cs1","seed":42}'
   ```
   The HTTP body accepts a discriminated `input` field — either `{"kind":"center", ...}` or `{"kind":"bbox", ...}` — see [docs/adr/0003-center-coordinate-input.md](docs/adr/0003-center-coordinate-input.md).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — full architectural design (MVP scope, roadmap, data flow, risks, libraries, testing methodology).
- [docs/adr/](docs/adr/) — architecture decision records.
  - [0001 — pipeline architecture, export targets, foundational stack](docs/adr/0001-pipeline-architecture.md)
  - [0002 — CS2 export format: known pieces and open questions](docs/adr/0002-cs2-export-format.md)
  - [0003 — center-coordinate input, target-tile registry, extent resolution](docs/adr/0003-center-coordinate-input.md)
  - [0004 — SRTM source strategy: ESA STEP for MVP, NASA EarthData for production](docs/adr/0004-srtm-source-strategy.md)

## Determinism contract

Every run is reproducible:
- All RNGs derive from `StageContext.seed`. The `random` module global is forbidden.
- Dict iteration that affects output is sorted.
- The DEM cache is content-addressed by `(provider, tile_id)` — SRTM 1-arc-second tiles are immutable.
- A golden-output regression test (`tests/golden/test_full_pipeline_determinism.py`) hashes the final heightmap PNG bytes and fails on drift.

## Attribution

- DEM data: NASA SRTM 1-arc-second global (public domain in the US; attribution recommended).
- Vector data: © OpenStreetMap contributors, licensed under the [ODbL](https://www.openstreetmap.org/copyright). Every export bundle includes an attribution notice.

## License

MIT — see [LICENSE](LICENSE).
