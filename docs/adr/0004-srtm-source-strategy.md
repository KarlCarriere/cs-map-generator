# ADR 0004: SRTM Source Strategy — ESA STEP for MVP, NASA EarthData for Production

- Status: Accepted
- Date: 2026-05-18
- Deciders: project leadership

## Context

The v0.1 MVP uses `SRTMDEMSource` (1-arc-second SRTM tiles, ≈ 30 m resolution) as the default
DEM provider. SRTM data is NASA-produced, originally distributed by USGS, and now mirrored by
several public archives. The two practically relevant sources for our pipeline are:

- **ESA STEP** (`https://step.esa.int/auxdata/dem/SRTMGL1/`). Public HTTPS mirror. No auth, no
  rate limit beyond reasonable politeness, no registration. Tiles are byte-identical to the
  authoritative USGS distribution.
- **NASA EarthData** (`https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/`). The authoritative
  source. Requires a free EarthData login and an OAuth bearer token in production usage. Has
  documented availability and SLA commitments; appropriate for commercial-grade pipelines.

The current implementation hardcodes the ESA STEP base URL via `Settings.srtm_base_url`. It
works offline once the cache is populated, which is the only path the MVP test suite
exercises.

## Decision

1. **ESA STEP is the MVP default.** Reasons:

   - Zero-friction. Contributors can run the pipeline against a real bbox with no account or
     token setup. This is critical for an open development model.
   - Identical bytes to the authoritative USGS tiles, so determinism via content-addressed
     cache is preserved.
   - The existing `SRTMDEMSource` adapter is left **unchanged** by this ADR. No code changes
     today; this is a documented strategy decision only.

2. **NASA EarthData is the planned commercial-grade adapter.** When we move toward public
   distribution or commercial release, we introduce a second `DEMSource` implementation
   (e.g., `EarthDataSRTMDEMSource`) that:

   - Reads an EarthData bearer token from a typed config field (env-driven, validated at
     startup, never hardcoded).
   - Implements the same `DEMSource` Protocol so the rest of the pipeline is unaffected.
   - Lives next to `SRTMDEMSource` in `infrastructure/dem/`. Selection happens in the
     composition root via `Settings.dem_provider`.

3. **Trigger conditions for the EarthData adapter** (any one is sufficient):

   - Before any **public release** that bundles, redistributes, or self-hosts DEM cache
     contents — see consequences below for the licensing reason.
   - Before **commercial launch** of the creator tool, where we want a vendor-backed SLA on
     the upstream data source.
   - If ESA STEP availability becomes a blocker for CI or staging (rate-limit, outage,
     change-of-URL).

4. **Licensing / redistribution posture**:

   - SRTM data itself is **U.S. government public domain** as released by NASA/USGS;
     attribution is recommended but not legally required.
   - **ESA STEP** is a redistribution mirror. We treat it as a fetch source only — we do not
     redistribute cached tiles ourselves and we do not bundle DEM tiles into shipped
     artifacts. The cache directory (`data/cache/`) is gitignored and explicitly out of any
     release tarball.
   - The `ExportManifest` already includes an attribution line; the README documents the
     attribution recommendation. No code change required.
   - Once we introduce a hosted commercial product, the EarthData adapter pulls bytes
     directly from the authoritative source and the licensing chain is unambiguous.

## Consequences

- v0.1 ships with the ESA STEP URL as the default and **no** EarthData credentials anywhere
  in the codebase, env, or settings. We cannot accidentally leak a token because we have
  none.
- A future PR will add `EarthDataSRTMDEMSource`. That PR's checklist must include: (a) typed
  config field with `pydantic-settings`, (b) startup validation that the token is present
  when `dem_provider == "earthdata"`, (c) integration test covering an unauthenticated 401
  surface as a typed error.
- Settings selection between providers is a one-line composition change in
  `interfaces/composition.py`; the application layer remains source-agnostic.
- We will **not** bundle DEM cache contents into any release. If the user ships their
  generated maps they ship only the PNG/JSON artifacts, never the raw upstream tiles.

## Status

Accepted. Move-to-next-step trigger: first PR proposing public distribution or commercial
release. At that point this ADR moves to "Supersedes" and a new ADR pins the EarthData
adapter as the production default.
