"""Cities: Skylines II export target.

Documented format pieces (Paradox modding dev diary, CS2 wiki, MOOB):
- Heightmap: 4096 × 4096 pixels, 16-bit grayscale, PNG or TIFF.
- World map: 4096 × 4096 pixels, 16-bit grayscale, PNG or TIFF; center 1024 × 1024 region must
  match the base heightmap pixel-for-pixel.

v0.2 additions (documented in ADR 0005):
- `water_mask.png`: 4096 × 4096 uint8 grayscale PNG (0 = land, 255 = water). The brief calls
  this the "single source of truth mask" — the heightmap has been carved upstream so the
  in-game water plane covers it, and the mask remains available for any future CS2 mod that
  wants to drive surface materials, decorations, or a depth-map derived layer.

Open questions tracked in `docs/adr/0002-cs2-export-format.md` (still applicable):
- TODO(adr-0002): height-scale-to-metres convention for CS2.
- TODO(adr-0002): world-map sea-level encoding vs. base heightmap datum.
- TODO(adr-0002): full binary map-package layout (we emit only the PNG layers + manifest today).

v0.2-specific open question (tracked in ADR 0005):
- Q5(adr-0005): does CS2 read a separate `water_depth.png`? No authoritative documentation
  found at the time of this ADR. We emit only the mask; if a depth layer turns out to be
  required, a future ADR pins the format and we add a `water_depth.png` artifact.
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

TARGET_ID = "cs2"
HEIGHTMAP_SIDE_PIXELS = 4096
WORLDMAP_SIDE_PIXELS = 4096
WORLDMAP_INNER_REGION_PIXELS = 1024
HEIGHTMAP_FILENAME = "heightmap.png"
WORLDMAP_FILENAME = "worldmap.png"
WATER_MASK_FILENAME = "water_mask.png"
ROADS_FILENAME = "roads.geojson"
MANIFEST_FILENAME = "manifest.json"
PNG_MIME = "image/png"


class CS2ExportTarget:
    target_id = TARGET_ID

    def __init__(self, reprojector: Reprojector) -> None:
        self._reprojector = reprojector

    def export(
        self,
        tile: MapTile,
        store: ArtifactStore,
        context: StageContext,
    ) -> ExportManifest:
        # Resample input heightmap to CS2's full 4096 × 4096 grid.
        base_pixels = resample_uint16_nearest(tile.heightmap.pixels, HEIGHTMAP_SIDE_PIXELS)
        heightmap_bytes = encode_uint16_grayscale_png(base_pixels)
        heightmap_entry = store.write(HEIGHTMAP_FILENAME, heightmap_bytes, context)

        worldmap_pixels = _build_worldmap(base_pixels)
        worldmap_bytes = encode_uint16_grayscale_png(worldmap_pixels)
        worldmap_entry = store.write(WORLDMAP_FILENAME, worldmap_bytes, context)

        water_mask_entry = _write_water_mask(tile.water_mask, HEIGHTMAP_SIDE_PIXELS, store, context)

        roads_wgs84 = self._reprojector.reproject_network(tile.road_network, Projection.wgs84())
        roads_bytes = encode_road_network_geojson(roads_wgs84, tile.bounds)
        roads_entry = _override_mime(
            store.write(ROADS_FILENAME, roads_bytes, context),
            GEOJSON_MIME,
        )

        artifacts = (heightmap_entry, worldmap_entry, water_mask_entry, roads_entry)
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
    if water_mask is None:
        mask_array = np.zeros((target_side, target_side), dtype=np.bool_)
    else:
        mask_array = water_mask.mask
        if mask_array.shape != (target_side, target_side):
            mask_array = resample_bool_nearest(mask_array, target_side)
    grayscale = np.where(mask_array, np.uint8(255), np.uint8(0)).astype(np.uint8)
    payload = encode_uint8_grayscale_png(grayscale)
    return _override_mime(
        store.write(WATER_MASK_FILENAME, payload, context),
        PNG_MIME,
    )


def _override_mime(entry: ArtifactEntry, mime: str) -> ArtifactEntry:
    return ArtifactEntry(name=entry.name, path=entry.path, sha256=entry.sha256, mime=mime)


def _build_worldmap(base_pixels: np.ndarray) -> np.ndarray:
    """Embed the base heightmap into the center 1024×1024 region of a 4096×4096 world map.

    Outside the center region we pad with the median elevation of the base heightmap. This is a
    placeholder strategy: TODO(adr-0002) — replace with real wide-context DEM fetch in v0.4.
    """
    inner = resample_uint16_nearest(base_pixels, WORLDMAP_INNER_REGION_PIXELS)
    pad_value = int(np.median(base_pixels))
    worldmap = np.full(
        (WORLDMAP_SIDE_PIXELS, WORLDMAP_SIDE_PIXELS),
        pad_value,
        dtype=np.uint16,
    )
    offset = (WORLDMAP_SIDE_PIXELS - WORLDMAP_INNER_REGION_PIXELS) // 2
    worldmap[
        offset : offset + WORLDMAP_INNER_REGION_PIXELS,
        offset : offset + WORLDMAP_INNER_REGION_PIXELS,
    ] = inner
    return worldmap


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
    epoch_offset = context.seed % (60 * 60 * 24 * 365)
    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    return (base + dt.timedelta(seconds=epoch_offset)).isoformat()
