# cs-mapgen

A deterministic GIS compiler that converts a real-world bounding box into engine-ready map artifacts for **Cities: Skylines 1** and **Cities: Skylines II**. Same inputs + same seed = byte-identical heightmaps.

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
     --out data/output/quebec-cs1 \
     --seed 42
   ```
   `--center` takes `LAT,LON` (latitude first, the human-natural order). The map is centred on that coordinate and extends 4 tiles in every cardinal direction for CS1 (10 for CS2) by default; override with `--radius-tiles N`. The legacy `--bbox west,south,east,north` flag (lon-first, matching W/S/E/N) is still supported for scripting workflows.

   A per-stage progress bar is rendered to stderr when stderr is a TTY. Disable it with `--no-progress` (or auto-disabled in CI / when stderr is captured). The JSON manifest is always written to stdout, so `cs-mapgen generate ... > manifest.json` still works.

5. Or generate a CS2 map (4096 × 4096 heightmap + worldmap):
   ```bash
   uv run cs-mapgen generate \
     --center 46.81,-71.21 \
     --target cs2 \
     --out data/output/quebec-cs2 \
     --seed 42
   ```

6. Or run the API:
   ```bash
   uv run uvicorn cs_mapgen.interfaces.http.app:app --reload
   curl -X POST http://localhost:8000/maps \
     -H "Content-Type: application/json" \
     -d '{"input":{"kind":"center","lat":46.81,"lon":-71.21},"target":"cs1","seed":42}'
   ```
   The HTTP body accepts a discriminated `input` field — either `{"kind":"center", ...}` or `{"kind":"bbox", ...}` — see [docs/adr/0003-center-coordinate-input.md](docs/adr/0003-center-coordinate-input.md).

## What gets generated

Every run writes the following to `--out`:

| File | Targets | Description |
| --- | --- | --- |
| `heightmap.png` | CS1, CS2 | 16-bit grayscale heightmap. 1081 × 1081 for CS1, 4096 × 4096 for CS2. Pixels under OSM water are carved to just below sea level so the in-game water plane covers them on import (v0.2). |
| `worldmap.png` | CS2 | 16-bit grayscale, 4096 × 4096. Centre 1024 × 1024 region matches the heightmap pixel-for-pixel. |
| `water_mask.png` | CS1, CS2 | 8-bit grayscale binary mask (0 = land, 255 = water). Aligned 1:1 with `heightmap.png`. The single source of truth for "this pixel is water"; pairs with the carved heightmap. Introduced in v0.2 — see [docs/adr/0005-water-mask-and-carving.md](docs/adr/0005-water-mask-and-carving.md). |
| `roads.geojson` | CS1, CS2 | OSM-derived road network as a WGS84 GeoJSON `FeatureCollection` (RFC 7946). One LineString per road segment; `properties` carry `highway_class` and `length_metres`. Useful in QGIS / leaflet / Mapbox — Cities: Skylines itself does **not** ingest road data. |
| `manifest.json` | CS1, CS2 | Reproducibility record: input bbox, seed, every artifact's SHA-256, and an `inputs_hash` that pins the full input set. `schema_version` is 2 since v0.2. |

## Loading the output into Cities: Skylines

The games consume only the PNG layers. Roads and zoning are placed by you in-game or in the Map Editor.

### Cities: Skylines II

1. Copy `heightmap.png` and `worldmap.png` into the Heightmaps folder (case-sensitive; create it if missing):
   - **Windows**: `%USERPROFILE%\AppData\LocalLow\Colossal Order\Cities Skylines II\Heightmaps\`
   - **macOS**: `~/Library/Application Support/Colossal Order/Cities Skylines II/Heightmaps/`
   - **Linux (Proton)**: `~/.steam/steam/steamapps/compatdata/<appid>/pfx/drive_c/users/steamuser/AppData/LocalLow/Colossal Order/Cities Skylines II/Heightmaps/`
2. Launch CS2 → **Editor** → **New** → **Map**.
3. Import the heightmap (and the matching worldmap when prompted). Save as a map.

Vertical scale and sea-level semantics for the CS2 map editor are not fully pinned in v0.1 — see open questions Q1–Q4 in [docs/adr/0002-cs2-export-format.md](docs/adr/0002-cs2-export-format.md). Expect to touch the height-scale and sea-level sliders in the editor on first import.

### Cities: Skylines 1

CS1's Map Editor accepts a 1081 × 1081 16-bit grayscale PNG via **Import Heightmap**. Default vertical scale is 0–1024 m; default sea level is 40 m.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — full architectural design (MVP scope, roadmap, data flow, risks, libraries, testing methodology).
- [docs/adr/](docs/adr/) — architecture decision records.
  - [0001 — pipeline architecture, export targets, foundational stack](docs/adr/0001-pipeline-architecture.md)
  - [0002 — CS2 export format: known pieces and open questions](docs/adr/0002-cs2-export-format.md)
  - [0003 — center-coordinate input, target-tile registry, extent resolution](docs/adr/0003-center-coordinate-input.md)
  - [0004 — SRTM source strategy: ESA STEP for MVP, NASA EarthData for production](docs/adr/0004-srtm-source-strategy.md)
  - [0005 — water mask, carving, pit-fill, coastline reconstruction (v0.2)](docs/adr/0005-water-mask-and-carving.md)

## Determinism contract

Every run is reproducible:
- All RNGs derive from `StageContext.seed`. The `random` module global is forbidden.
- Dict iteration that affects output is sorted.
- The DEM cache is content-addressed by `(provider, tile_id)` — SRTM 1-arc-second tiles are immutable.
- The GeoJSON encoder dumps with `sort_keys=True` and emits edges in the order produced by `PrepareRoadsStage` (sorted by `(source, target)`).
- A golden-output regression test (`tests/golden/test_full_pipeline_determinism.py`) hashes the final heightmap PNG bytes and fails on drift.

## Attribution

- DEM data: NASA SRTM 1-arc-second global (public domain in the US; attribution recommended).
- Vector data: © OpenStreetMap contributors, licensed under the [ODbL](https://www.openstreetmap.org/copyright). Every export bundle includes an attribution notice.

## License

MIT — see [LICENSE](LICENSE).
