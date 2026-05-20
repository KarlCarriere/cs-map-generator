# ADR 0005: Water — Mask, Carving, Pit-Fill, and Coastline Reconstruction

- Status: Accepted
- Date: 2026-05-19
- Deciders: project leadership
- Supersedes: nothing (v0.1 had no water layer).
- Touches: ADR 0001 (Reprojector port grows a `reproject_water_features` method),
  ADR 0002 (CS2 water encoding open questions parked here).

## Context

`v0.1` ships terrain + roads. The follow-up `v0.2` adds water — and water is not one decision
but a family of them:

1. **How is "water" encoded for Cities: Skylines 1 and 2?** The games consume a single
   16-bit grayscale heightmap; neither documents a separate "water layer" PNG channel that
   reliably ships across map editor versions. Yet the game's water plane is driven by the
   heightmap: anywhere terrain falls below sea level, the plane fills it.
2. **How do we represent and produce that mask deterministically?** The mask drives the
   heightmap carve AND is an explicit output artifact downstream tools / future mods will
   want.
3. **Hydrology before water carving.** Real DEMs contain spurious single-cell pits (sensor
   noise) and small flat depressions that any flow-based analysis (rivers, drainage) must
   condition out. CS1/CS2 do not care, but if we ever extend `v0.3+` with river-carving or
   flow accumulation we want a hydrologically conditioned float DEM, not the raw one.
4. **Coastline reconstruction.** OSM ships coastline as an open polyline with land on the
   left, sea on the right. To use it as a polygon mask we must close it against the bbox
   boundary. The naive closure (just concatenate the bbox corners) is wrong for any bbox
   whose coastline does not enter and exit on the same side.

This ADR records the choices for all four. A companion ADR was considered for coastline
reconstruction alone; we kept it folded here because the four decisions are tightly coupled
and reading them together is more honest than reading them apart.

## Decision

### 1. CS1/CS2 water encoding: **carve + emit a separate mask**

- The `QuantizeHeightmapStage` clamps every pixel under the water mask to
  `sea_level_metres - epsilon`, where epsilon is one uint16 quantisation step
  (`height_scale / 65535`, ~1.56 cm at the default 1024 m CS1 scale). At runtime the in-game
  water plane covers the carved pixels cleanly.
- We additionally emit `water_mask.png` (uint8 0/255 grayscale, aligned 1:1 with
  `heightmap.png`) for both CS1 and CS2 export bundles. This file is:
  - An inspection artifact (open it in any image viewer to see where the generator decided
    water lives).
  - The single source of truth for any future CS2 mod (see `docs/cs2-road-importer-plan.md`)
    that wants to drive surface materials, decorations, or a depth layer from the same mask.

Rationale:

- Carving alone leaves no metadata. A consumer that loads `heightmap.png` cannot recover
  "this pixel was carved because of OSM `natural=water`" vs. "this pixel is naturally below
  sea level". The mask is metadata.
- The mask alone leaves the in-game water plane stuck above terrain that should be sea bed.
  Carving alone is necessary for the game to display water without the user touching the
  Map Editor's terrain tools.
- Both. Belt + suspenders.

Carving rule (precise):

```python
quantisation_step_metres = height_scale_metres / 65535
carve_target_metres = sea_level_metres - quantisation_step_metres
# only carve cells whose float elevation is ABOVE the carve target — Dutch-polder cells
# already below sea level are left untouched so real bathymetry detail is preserved.
```

### 2. Pit-fill via **pysheds**, before quantisation, AFTER reproject+resample

Algorithm: `pysheds.grid.Grid.fill_pits` (single-cell) followed by
`pysheds.grid.Grid.fill_depressions` (Planchon-Darboux / Wang & Liu).

- We run on the **float, working-CRS, target-resolution** elevation array — never on the
  uint16 heightmap (a 1-bit difference at the default 1024 m scale is ~1.5 cm; depressions
  smaller than that disappear into round-off if conditioning happens post-quantise).
- pysheds is pinned to `~=0.5` in `pyproject.toml`. The 0.5 release (Aug 2025) restores
  numpy 2.x compatibility, drops `pgrid`/`rfsm` (we use `sgrid`/Numba via `pysheds.grid`),
  and leaves the methods we call (`fill_pits`, `fill_depressions`) unchanged on their
  signatures. Re-verify before bumping the pin.

Determinism: pysheds operations on a fixed numpy array with a fixed library version are
deterministic. We additionally swap nodata cells to a low sentinel (-9999 m) before running
the fill — this prevents pysheds from treating nodata as walls that the flood algorithm
can propagate around in unstable ways. After the fill we restore the sentinel positions; the
`nodata_mask` carried on `PreparedTerrain` is the authoritative source of "this cell was
missing".

Why not hand-roll the pit-fill in NumPy? Two reasons:
- Numba-accelerated; orders of magnitude faster at 4096×4096 than pure Python.
- Planchon-Darboux is subtle (priority queue with tie-breaking). Borrowing a reviewed
  implementation is the right call.

### 3. River carving via OSM `waterway=*` lines, **buffered to class-specific widths**

`waterway` values we accept and their default rasterisation widths (in metres):

| class    | default width | rationale                                    |
|----------|---------------|----------------------------------------------|
| `river`  | 20 m          | Median real-world width; visible at 16 m/px. |
| `stream` | 5 m           | Sub-pixel at CS1 scale; included for CS2.    |
| `canal`  | 15 m          | Slightly wider than typical urban canals.    |

Anything outside this allowlist (`drain`, `ditch`, `brook`, …) is **skipped**. They are too
narrow to register at heightmap pixel resolution and would introduce noise.

The widths are configurable via `PrepareWaterStage(waterway_widths_metres=…)`. The mapping
above is the v0.2 default. We rasterise by buffering the LineString to `width / 2` and
burning the resulting polygon — same code path as `natural=water` polygons, same
deterministic ordering rules.

### 4. Coastline reconstruction: **bbox closure via polygonize**

OSM `natural=coastline` ships as open polylines with **land on the left, sea on the right**.
We:

1. Clip each segment to the working-CRS bbox.
2. Union the clipped segments with the bbox boundary loop.
3. Pass the union to `shapely.ops.polygonize`, which returns every closed region.
4. Pick the **sea** regions by sampling each candidate's interior representative point and
   testing which side of the nearest coastline segment it lies on (right-of-line ⇒ sea).
5. Return a `MultiPolygon` of sea regions; the rasteriser burns it into the water mask.

Pathological cases we explicitly defer (raise `InvalidBoundsError`, consistent with v0.1
risk #2):

- bboxes crossing the antimeridian (±180°).
- bboxes containing or near a pole.
- bboxes with **no** coastline crossing the boundary AND containing closed coastlines
  entirely inside (islands surrounded by sea): the polygonize trick correctly assembles the
  island polygons, but the rightside test cannot distinguish "this is the inside of an
  island" from "this is the inside of the sea" without external context. We accept this as a
  documented limitation; a future ADR pins the resolution (likely OSM relation `natural=sea`
  plus `place=island` cross-referencing).

### 5. Data-model addition: `WaterMask`, `WaterFeatures`

- `WaterMask` is a frozen value object: `mask: NDArray[bool]`, `transform: tuple[float, ...]`,
  `crs: Projection`. Lives in `cs_mapgen.domain.water`. Re-exported from
  `cs_mapgen.domain.raster` for backward compatibility.
- `WaterFeatures` is a transient DTO inside the domain layer carrying the raw, ingested-but-
  not-yet-rasterised geometry across the application/infrastructure boundary. We keep it in
  the domain rather than in `application/` because tests must be able to construct one
  without importing infrastructure.
- We deliberately did **not** add a `RiverNetwork` graph-like object. Rivers, in v0.2, are
  rasterised straight from the `Waterway` line-tuples. A graph-like representation only
  earns its keep when flow-accumulation or river-mouth-to-source ordering matters (a v0.3+
  feature).

### 6. Manifest schema: `schema_version` bump to 2

- Adds `water_mask.png` to the artifact set for both CS1 and CS2.
- Adds `water_mask_sha256` into the `inputs_hash` payload so determinism regressions on the
  mask itself fail the golden-output test.
- Downstream consumers MUST treat unknown `schema_version > 2` as forward-incompatible.

### 7. CS2 water-depth: **open question, parked**

The brief asks us to investigate whether CS2 expects a `water_depth.png` channel. We could
find **no authoritative Paradox documentation** confirming or refuting it as of 2026-05-19.
Community modding tools (MOOB on Thunderstore) appear to round-trip the heightmap and let
the editor's water-level slider handle depth, which is consistent with "no separate depth
file". We therefore:

- Emit only `water_mask.png` for CS2 in v0.2.
- Track the open question below; if a depth file turns out to be required, a future ADR
  pins the format and we add a `water_depth.png` artifact (and bump `schema_version` again).

## Consequences

- The pipeline gains four new stages: `IngestWaterStage`, `ConditionTerrainStage`,
  `PrepareWaterStage`, `QuantizeHeightmapStage`. The v0.1 stage `PrepareTerrainStage` is
  refactored to return a float `PreparedTerrain` instead of a quantised `Heightmap`. The
  final pipeline order is now:

      IngestDEM → IngestRoads → IngestWater → PrepareTerrain → ConditionTerrain →
      PrepareWater → QuantizeHeightmap → PrepareRoads → ComposeMap → ExportMap

- The `Reprojector` Protocol grows a `reproject_water_features` method. `PyprojReprojector`
  implements it; the `IdentityReprojector` fake in `tests/_fakes.py` is updated.
- pysheds is now a runtime dependency. The lockfile gets larger; numba pulls in LLVM. This
  is the price of fast pit-fill; we accept it.
- **Licence**: pysheds is GPL-3. We invoke it as a library at runtime within an
  MIT-licensed pipeline — the standard "linking" / "use" scenario. Distributing the
  generated artifacts (heightmap PNG, water mask PNG, manifest) is **not** a derivative
  work of pysheds and is unaffected by GPL-3. Re-verify implications before any commercial
  redistribution that bundles pysheds itself; the ADR pin gives us a single place to revisit.
- The CS1 and CS2 export bundles grow one file (`water_mask.png`). Existing consumers
  reading only `heightmap.png` keep working; consumers using the manifest pick up the new
  entry automatically.
- The golden-output determinism test must record a new baseline. The brief calls this out
  explicitly and the hashes for `heightmap.png`, `water_mask.png`, and `manifest.json` all
  change vs. v0.1. They are committed in this PR.
- Antimeridian / polar bboxes still raise `InvalidBoundsError`. The coastline reconstructor
  has the same constraint — surfaced as the same error type, no new exception class.

## Open Questions

- **Q1(adr-0005)** — does CS2 read a separate `water_depth.png` or equivalent? See §7.
  Resolution requires either Paradox documentation or an empirical mod-API survey. We do
  not block v0.2 on this; the mask is sufficient for the editor's manual water-level flow.
- **Q2(adr-0005)** — `WATERWAY_WIDTH_METRES` defaults are gut-feel. They produce
  plausible-looking rivers on the test fixture but a real-world calibration pass (compare
  vs. satellite imagery for a few well-known bboxes) is owed before v1.0.
- **Q3(adr-0005)** — coastline-side detection is point-sampling-based; complex bays with
  multiple coastlines snaking across the bbox can fool the nearest-line heuristic. A future
  pass should use `shapely.ops.unary_union` + winding-number rules. The current implementation
  is correct for the v0.2 test fixture and reasonable for typical CS-sized bboxes.
- **Q4(adr-0005)** — pysheds' `fill_depressions` does not always converge on degenerate
  inputs (all-flat DEMs). We do not exercise this path in tests because flat synthetic DEMs
  trip the pre-existing `valid_max - valid_min == 0` branch in `_linear_stretch` first.
  Surface as a real bug only when a user reports it.
- **Q5(adr-0005)** — DEM datum. v0.2 assumes SRTM-style "metres above mean sea level". A
  future DEM provider with a non-MSL datum will produce a carve offset by that datum. Track
  alongside the `EarthDataSRTMDEMSource` work in ADR 0004.

## Status

Accepted. Revisit when Q1 is resolved (water-depth file question), when a flow-accumulation
feature lands in v0.3+ (`RiverNetwork` may finally earn its keep), or when antimeridian
support is required.
