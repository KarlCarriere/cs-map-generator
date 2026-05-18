# ADR 0001: Pipeline Architecture, Export Targets, and Foundational Stack

- Status: Accepted
- Date: 2026-05-18
- Deciders: project leadership
- Superseded in part by: [ADR 0003](./0003-center-coordinate-input.md) — the single-bbox input assumption is generalised to a tagged `MapExtent` (center+radius **or** bbox) resolved to a `GeoBounds` at the interface boundary. The internal pipeline still consumes a `GeoBounds`; the addition is at the user-facing layer only.

## Context

We are building a deterministic compiler that turns a real-world bounding box into a Cities: Skylines 1 (CS1) and Cities: Skylines II (CS2) map package. The system must be reproducible, debuggable, and extensible. It must also work offline once the source DEM and OSM data have been cached.

Key forces:

- GIS dependencies (GDAL, rasterio, geopandas) are notoriously hard to install on raw host machines; their versions are tightly coupled.
- The user-facing input is a WGS84 bbox; the working unit must be metric or all distance/topology math becomes wrong.
- CS1 and CS2 have different heightmap dimensions and the CS2 binary asset layout is partially undocumented today.
- Determinism is a hard product requirement (same input + same seed = byte-identical output).

## Decision

1. **Pipeline as a sequence of pure stages.** Each stage implements a `Stage` Protocol with a typed `run(inputs, context) -> output`. Side effects are isolated behind injected ports (`DEMSource`, `OSMSource`, `Reprojector`, `ArtifactStore`, `ExportTarget`). The domain layer has zero framework dependencies.

2. **Two export targets from day one.** `CS1ExportTarget` (1081×1081, 16-bit grayscale PNG) and `CS2ExportTarget` (4096×4096, 16-bit grayscale PNG + 4096×4096 world map). Both implement the same `ExportTarget` Protocol so adding CS3 / Unity / Unreal later is a matter of a new adapter — no changes to the domain or application layers.

3. **SRTM 30 m as the default DEM source**, behind a pluggable `DEMSource` Protocol. Copernicus GLO-30, USGS 3DEP, ALOS, and local GeoTIFFs are documented future implementations of the same Protocol. SRTM works offline once cached.

4. **CLI and FastAPI surfaces share the same pipeline.** Both surfaces are translators: bind input -> call `Pipeline.run` -> serialize result. They contain no business logic. `typer` was chosen over `click` for the CLI because its type-annotation-driven UX matches the rest of the codebase with less boilerplate, while still using Click underneath.

5. **`uv` for dependency management.** Lockfile-native, fast, friendly to the dev container. Pinned `uv` version inside the Dockerfile.

6. **Dev Container is the supported development environment.** The Dockerfile is based on `ghcr.io/osgeo/gdal:ubuntu-small-3.10.0` (GDAL + Python 3.12 + system GDAL bindings) and installs the rest of the stack via `uv sync` on top. Host installs of GDAL are explicitly out of scope.

7. **Working CRS is a local metric projection chosen at ingest time** (UTM zone derived from bbox centroid for typical bboxes; equal-area fallback for very large extents). The CRS is carried explicitly on every raster and vector value object.

8. **Determinism contracts are testable.** A golden-output test hashes the final heightmap PNG bytes; all RNGs derive from `StageContext.seed`; dict-derived iteration that affects output is sorted.

## Consequences

- The team commits to working through the dev container; "works on my machine" is not a defense.
- Adding new GIS features (water, forests, land use) means adding stages and ports without touching CLI or HTTP code.
- Swapping DEM provider or export target is a one-file change at the infrastructure layer.
- Some boilerplate cost up front (Protocols, frozen dataclasses, no shortcuts through globals) — paid back the first time we hit a determinism regression or a CS2 format change.
- Pydantic stays at the boundary (config, FastAPI bodies). Domain uses frozen dataclasses to keep the core framework-free.

## Status

Accepted. Revisit when introducing the v0.2 water layer (may pressure the `Reprojector` Protocol to grow a `reproject_mask` method).
