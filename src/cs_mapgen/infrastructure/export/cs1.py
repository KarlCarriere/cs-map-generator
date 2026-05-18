"""Cities: Skylines 1 export target.

Format reference (Paradox wiki + community tooling):
- 1081 × 1081 pixels, 16-bit grayscale PNG.
- Map side: 17.28 km. One pixel ~16 m.
- Default vertical scale: 0–1024 m. Default sea level: 40 m.

The heightmap PNG is the only required artifact. We also emit a `manifest.json` with provenance
data so the export bundle is reproducibility-auditable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from cs_mapgen.application.ports import ArtifactStore, Reprojector
from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import Projection
from cs_mapgen.domain.manifest import ArtifactEntry, ExportManifest
from cs_mapgen.domain.map_tile import MapTile
from cs_mapgen.infrastructure.export._geojson import (
    GEOJSON_MIME,
    encode_road_network_geojson,
)
from cs_mapgen.infrastructure.export._png import encode_uint16_grayscale_png, resample_uint16_nearest

TARGET_ID = "cs1"
HEIGHTMAP_SIDE_PIXELS = 1081
HEIGHTMAP_FILENAME = "heightmap.png"
ROADS_FILENAME = "roads.geojson"
MANIFEST_FILENAME = "manifest.json"


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

        roads_wgs84 = self._reprojector.reproject_network(tile.road_network, Projection.wgs84())
        roads_bytes = encode_road_network_geojson(roads_wgs84, tile.bounds)
        roads_entry = _override_mime(
            store.write(ROADS_FILENAME, roads_bytes, context),
            GEOJSON_MIME,
        )

        manifest = ExportManifest(
            target=TARGET_ID,
            bounds=tile.bounds,
            inputs_hash=_compute_inputs_hash(tile, context),
            seed=context.seed,
            artifacts=(heightmap_entry, roads_entry),
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
        "road_edge_count": tile.road_network.edge_count,
        "road_node_count": tile.road_network.node_count,
    }
    canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _deterministic_timestamp(context: StageContext) -> str:
    # The manifest needs a timestamp, but a wall-clock `now()` breaks byte-for-byte determinism.
    # We derive a deterministic UTC timestamp from the seed so reruns with the same seed produce
    # the same manifest. Real wall-clock timestamps are tracked separately via the logger.
    epoch_offset = context.seed % (60 * 60 * 24 * 365)
    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    return (base + dt.timedelta(seconds=epoch_offset)).isoformat()
