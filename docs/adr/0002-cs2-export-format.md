# ADR 0002: CS2 Export Format — Known Pieces and Open Questions

- Status: Proposed
- Date: 2026-05-18

## Context

Cities: Skylines II (CS2) uses a different map import format than CS1. The publicly documented pieces (Paradox modding dev diaries, CS2 wiki, the in-game Map Editor) confirm:

- **Heightmap**: 4096 × 4096 pixels, 16-bit grayscale, PNG or TIFF.
- **World map**: 4096 × 4096 pixels, 16-bit grayscale, PNG or TIFF; the **center 1024 × 1024 region must match the base heightmap** pixel-for-pixel.
- **Install path** (for end-user use, not production export): `%USERPROFILE%/AppData/LocalLow/Colossal Order/Cities Skylines II/Heightmaps/`. Folder name is case-sensitive.

What is NOT publicly documented to a reproducible engineering standard:

- The exact binary layout of CS2's full **map package** (the bundle containing heightmap, world map, water layer, surface overlays, road network, decorations).
- The expected **sea-level offset semantics** for the world map (is sea level encoded the same way across heightmap and world map? Is there an explicit datum?).
- The **height-scale** convention for CS2 (CS1's 0–1024 m default is well-known; CS2's effective vertical range is less precisely documented and may depend on map-editor settings rather than the file format).
- The road network and decoration formats inside the bundled map asset.

## Decision

For v0.1 MVP, `CS2ExportTarget` will produce **only the documented PNG layers**:

1. `heightmap.png` — 4096 × 4096, 16-bit grayscale.
2. `worldmap.png` — 4096 × 4096, 16-bit grayscale, with the center 1024 × 1024 matching the heightmap.
3. `manifest.json` — `ExportManifest` with input hash, bounds, seed, sha256 of every artifact.

The pipeline composes these into a directory that can be dropped into the CS2 Heightmaps folder for **manual** import via the Map Editor. We do not fabricate the binary map-package layout. Anything we are not confident about is marked `TODO(adr-0002)` in the codebase.

Open questions tracked here:

- **Q1**: What is the canonical height-scale-to-meter mapping in CS2's map editor? Reference: Paradox modding dev diary #2 + community tooling (MOOB on Thunderstore) for empirical measurements.
- **Q2**: World-map sea-level encoding — does the world map use the same uint16 normalization as the base heightmap, or is it baselined to a separate datum?
- **Q3**: For wide-context world maps where real DEM data extends beyond the playable bbox, what's the expected resolution per pixel in the world-map's 4096 × 4096 grid?
- **Q4**: Once the binary map-package layout is documented or reverse-engineered, where does the road network slot in? Is there an editor-only intermediate or a fully baked asset?

Where to look to resolve:

- Paradox modding documentation (https://www.paradoxinteractive.com/games/cities-skylines-ii/modding).
- CS2 Wiki: https://cs2.paradoxwikis.com/Map_Creation.
- MOOB and community modding tools on Thunderstore (https://thunderstore.io/c/cities-skylines-ii/).
- Paradox forum threads on map-editor height import.

## Consequences

- v0.1 CS2 output is import-ready for the in-game Map Editor (PNGs in the right place) but is not a one-click "drop in and play" asset.
- A v0.2 or later ADR will supersede this once the binary layout is locked.
- We do not block MVP on this decision. We do block production-grade CS2 packaging on resolving Q1–Q4.

## Status

Proposed. Will move to Accepted once the v0.1 export ships and is validated against the CS2 Map Editor end-to-end.
