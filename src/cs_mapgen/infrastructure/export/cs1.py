"""Cities: Skylines 1 export target.

Format reference (Paradox wiki + community tooling):
- 1081 × 1081 pixels, 16-bit grayscale PNG.
- Map side: 17.28 km. One pixel ~16 m.
- Default vertical scale: 0–1024 m. Default sea level: 40 m.

v0.2 additions (documented in ADR 0005):
- `water_mask.png`: 1081 × 1081 uint8 grayscale PNG (0 = land, 255 = water). Aligned 1:1 with
  `heightmap.png`. The mask is the single source of truth for "this pixel is water" — the
  heightmap has already been carved upstream by `QuantizeHeightmapStage` so the in-game water
  plane covers the mask cleanly when imported via the CS1 Map Editor.
- The manifest's `schema_version` is bumped to 2 (see `cs_mapgen.domain.manifest`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import numpy as np

from cs_mapgen.application.ports import ArtifactStore, Reprojector
from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import Projection
from cs_mapgen.domain.manifest import ArtifactEntry, ExportManifest
from cs_mapgen.domain.map_tile import MapTile
from cs_mapgen.domain.water import WaterMask
from cs_mapgen.infrastructure.export._geojson import (
    GEOJSON_MIME,
    encode_road_network_geojson,
)
from cs_mapgen.infrastructure.export._png import (
    encode_uint16_grayscale_png,
    encode_uint8_grayscale_png,
    resample_bool_nearest,
    resample_uint16_nearest,
)

TARGET_ID = "cs1"
HEIGHTMAP_SIDE_PIXELS = 1081
HEIGHTMAP_FILENAME = "heightmap.png"
WATER_MASK_FILENAME = "water_mask.png"
ROADS_FILENAME = "roads.geojson"
MANIFEST_FILENAME = "manifest.json"
PNG_MIME = "image/png"


class CS1ExportTarget:
    target_id = TARGET_ID

    def __init__(self, reprojector: Reprojector) -> None:
        self._reprojector = reprojector

    def export(
        self,
        tile: MapTile,
        store: ArtifactStore,
        context: StageContext,
    ) -> ExportManifest:
        pixels = tile.heightmap.pixels
        if pixels.shape != (HEIGHTMAP_SIDE_PIXELS, HEIGHTMAP_SIDE_PIXELS):
            pixels = resample_uint16_nearest(pixels, HEIGHTMAP_SIDE_PIXELS)

        heightmap_bytes = encode_uint16_grayscale_png(pixels)
        heightmap_entry = store.write(HEIGHTMAP_FILENAME, heightmap_bytes, context)

        water_mask_entry = _write_water_mask(tile.water_mask, HEIGHTMAP_SIDE_PIXELS, store, context)

        roads_wgs84 = self._reprojector.reproject_network(tile.road_network, Projection.wgs84())
        roads_bytes = encode_road_network_geojson(roads_wgs84, tile.bounds)
        roads_entry = _override_mime(
            store.write(ROADS_FILENAME, roads_bytes, context),
            GEOJSON_MIME,
        )

        artifacts = (heightmap_entry, water_mask_entry, roads_entry)
        manifest = ExportManifest(
            target=TARGET_ID,
            bounds=tile.bounds,
            inputs_hash=_compute_inputs_hash(tile, context),
            seed=context.seed,
            artifacts=artifacts,
            created_at_utc=_deterministic_timestamp(context),
        )

        manifest_bytes = manifest.to_json().encode("utf-8")
        manifest_entry = store.write(MANIFEST_FILENAME, manifest_bytes, context)

        # Re-emit a manifest that includes itself as an artifact entry — this is the contract
        # exposed to downstream tools (so the manifest can be verified end-to-end).
        return ExportManifest(
            target=manifest.target,
            bounds=manifest.bounds,
            inputs_hash=manifest.inputs_hash,
            seed=manifest.seed,
            artifacts=(*manifest.artifacts, manifest_entry),
            created_at_utc=manifest.created_at_utc,
        )


def _write_water_mask(
    water_mask: WaterMask | None,
    target_side: int,
    store: ArtifactStore,
    context: StageContext,
) -> ArtifactEntry:
    """Write `water_mask.png` (uint8 0/255 PNG) aligned 1:1 with the heightmap.

    When the pipeline ran without a water source (legacy v0.1 paths) the tile carries no mask
    and we still emit a zero-filled PNG. This keeps the artifact set stable across runs and
    avoids "this file sometimes appears, sometimes doesn't" being a determinism trap.
    """
    if water_mask is None:
        mask_array = np.zeros((target_side, target_side), dtype=np.bool_)
    else:
        mask_array = water_mask.mask
        if mask_array.shape != (target_side, target_side):
            mask_array = resample_bool_nearest(mask_array, target_side)
    # 0 = land, 255 = water — the highest contrast representation. Downstream CS2 mods can
    # binarise on >127 if they want a hard cut.
    grayscale = np.where(mask_array, np.uint8(255), np.uint8(0)).astype(np.uint8)
    payload = encode_uint8_grayscale_png(grayscale)
    return _override_mime(
        store.write(WATER_MASK_FILENAME, payload, context),
        PNG_MIME,
    )


def _override_mime(entry: ArtifactEntry, mime: str) -> ArtifactEntry:
    # The artifact store has no per-extension MIME table — it returns a generic
    # `application/octet-stream`. The export target is the authoritative source of MIME for the
    # artifacts it produces, so we replace the placeholder before sealing the manifest.
    return ArtifactEntry(name=entry.name, path=entry.path, sha256=entry.sha256, mime=mime)


def _compute_inputs_hash(tile: MapTile, context: StageContext) -> str:
    payload = {
        "bounds": {
            "west": tile.bounds.west,
            "south": tile.bounds.south,
            "east": tile.bounds.east,
            "north": tile.bounds.north,
            "crs_epsg": tile.bounds.crs.epsg,
        },
        "seed": context.seed,
        "target": TARGET_ID,
        "heightmap_pixels_sha256": hashlib.sha256(tile.heightmap.pixels.tobytes()).hexdigest(),
        "water_mask_sha256": _hash_water_mask(tile.water_mask),
        "road_edge_count": tile.road_network.edge_count,
        "road_node_count": tile.road_network.node_count,
    }
    canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _hash_water_mask(mask: WaterMask | None) -> str:
    if mask is None:
        return "no_water"
    return hashlib.sha256(mask.mask.tobytes()).hexdigest()


def _deterministic_timestamp(context: StageContext) -> str:
    # The manifest needs a timestamp, but a wall-clock `now()` breaks byte-for-byte determinism.
    # We derive a deterministic UTC timestamp from the seed so reruns with the same seed produce
    # the same manifest. Real wall-clock timestamps are tracked separately via the logger.
    epoch_offset = context.seed % (60 * 60 * 24 * 365)
    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    return (base + dt.timedelta(seconds=epoch_offset)).isoformat()
