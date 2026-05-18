# ADR 0003: Center-Coordinate Input, Target-Tile Registry, and Extent Resolution

- Status: Accepted
- Date: 2026-05-18
- Deciders: project leadership
- Supersedes: parts of ADR 0001 that assume `GeoBounds` is the only user input shape.

## Context

ADR 0001 declared the user-facing input as a single WGS84 bounding box. That is the natural
shape for scripting and power-user workflows, but it is not the natural shape for a Cities:
Skylines user, who reasons about a square grid of in-game tiles centred on a starting tile.
Requiring the user to compute a bbox from a coordinate is friction and a frequent source of
off-by-one or off-by-projection mistakes (longitude shrinks toward the poles).

We also did not have a single place where each game's tile geometry lived. The CS1 export
target knew its heightmap is 1081×1081 over 17.28 km, and the CS2 export target knew its
heightmap is 4096×4096, but the per-tile-side and the full grid dimension were not first-class
data anywhere. Both the extent resolver and the export targets need them, so they need to live
somewhere both layers can read.

## Decision

1. **Two equivalent input shapes**: `MapExtent` is a tagged union in the domain
   (`CenterExtent` | `BoundsExtent`) discriminated by a `kind` literal.

   - `CenterExtent(center: GeoPoint, radius_tiles: int, target_id: str)` is the natural CS UX.
     The centre tile sits at `center`, and the playable area extends `radius_tiles` tiles in
     every cardinal direction.
   - `BoundsExtent(bounds: GeoBounds)` is the explicit-bbox power-user path, kept for parity.

   The pipeline itself still receives a `GeoBounds`. The translation happens at the interface
   boundary (CLI/HTTP) by calling `resolve_extent(extent: MapExtent) -> GeoBounds`. Nothing in
   `application/stages/*` or `infrastructure/*` cares about the input shape.

2. **`TargetSpec` registry in `cs_mapgen.domain.target_specs`**: a small, frozen registry
   mapping `target_id → TargetSpec(tile_side_metres, grid_dimension, default_radius_tiles)`. It
   lives in the domain because the numbers are intrinsic to each game, not deployment config,
   and both the extent resolver (pure domain logic) and the export target adapters
   (infrastructure) need to read them.

   The registry is the **single source of truth** for tile geometry. Hardcoding
   `tile_side_metres` anywhere else in the codebase is a defect.

   | target | tile_side_metres | grid_dimension | default_radius_tiles | total_side |
   |--------|------------------|----------------|----------------------|------------|
   | `cs1`  | 1920.0           | 9              | 4                    | 17.28 km   |
   | `cs2`  | 623.3            | 21             | 10                   | 13.09 km   |

3. **CS2 tile-side value**: we pin **623.3 m**. Sources:

   - The Paradox CS2 wiki documents 4096×4096 heightmap + 441-tile map but does **not** publish
     a per-tile side or an authoritative total-map-side in km.
   - Community measurements (en.number13.de, gameslearningsociety, gamerant cross-reference)
     consistently report ≈ 623.3 m per tile, which is internally consistent with the
     publicly cited "441 tiles, 171.33 km² total" (`√(171.33 / 441) ≈ 0.6233 km`).
   - Paradox marketing has rounded this down to "600 m × 600 m". We pin the precise community
     measurement and mark the constant with `TODO(adr-0003): verify CS2 tile-side metres`
     so that the value is re-verified against an authoritative Colossal Order spec before
     commercial release.

4. **Lat/lon → metres math**: a **local equirectangular approximation** around the centre
   latitude. Justification: CS-sized maps are at most ~17.3 km (CS1) or ~13.1 km (CS2) per
   side. Equirectangular error vs. WGS84 geodesic at that scale is < 0.1% of one tile across
   the latitude band we accept ([-85°, +85°]). It is pure Python, has no `pyproj` dependency
   in the application layer, is trivially auditable, and is deterministic. Geodesic precision
   is overkill here. The earth radius used is the WGS84 mean radius (6 371 008.8 m).

5. **Validation rules**:

   - `radius_tiles ≥ 0` (a zero radius collapses to a one-tile map; useful for tests).
   - `radius_tiles ≤ TargetSpec.max_radius_tiles` (cannot exceed the in-game grid).
   - `|latitude| ≤ 85°` for the centre. Above 85° we are outside the UTM-supported band that
     the v0.1 working CRS already enforces; we reject earlier with a typed error so the user
     gets a clear message rather than a reprojection failure later.
   - Antimeridian crossing is rejected. UTM is undefined across ±180°; v0.1 working CRS does
     not support this case (consistent with ADR 0001).
   - Pole overflow is rejected (a large radius near the pole could push `north > 90°`).

   All failures raise `ExtentResolutionError` (subclass of `InvalidExtentError`), translated to
   `400 Bad Request` (HTTP) or `BadParameter` (CLI).

6. **CLI shape**: `--center` (lat,lon — natural human order) and `--bbox`
   (west,south,east,north — lon-first to match W/S/E/N geographic order) are mutually
   exclusive. `--radius-tiles` is optional and defaults from the registry based on `--target`.
   Passing both flags returns a non-zero exit with a usage error mentioning both.

7. **HTTP shape**: `POST /maps` body uses a Pydantic v2 discriminated union on
   `input.kind ∈ {"center", "bbox"}`. Malformed payloads (missing or invalid `kind`) return 422
   from FastAPI's default validation handler.

## Consequences

- Adding more input shapes later (e.g., `GpsAndRadius`, `NamedRegion`, `OsmRelation`) means
  adding a new variant to the `MapExtent` tagged union plus a branch in `resolve_extent`. No
  other layer changes.
- The pipeline's determinism contract is **preserved**: `resolve_extent` is pure, and when the
  computed `GeoBounds` from a `CenterExtent` matches what a `BoundsExtent` would produce, the
  golden-output test continues to pass byte-for-byte. This is itself a property we test.
- Adding a future target (CS3, Unity Terrain) means a new `TargetSpec` registry entry plus an
  `ExportTarget` adapter — same one-file-change story as adding a DEM provider.
- We have committed to re-verifying the CS2 tile-side value before public release. The TODO
  ties the constant to this ADR so the verification cannot quietly fall off the radar.

## Status

Accepted. Re-open when an authoritative Colossal Order spec for the CS2 tile-side lands, or
when a third input shape arrives.
