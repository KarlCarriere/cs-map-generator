"""Shared fakes for pipeline tests. Deterministic, network-free, GDAL-free."""

from __future__ import annotations

import hashlib

import numpy as np

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.manifest import ArtifactEntry, ExportManifest
from cs_mapgen.domain.map_tile import MapTile
from cs_mapgen.domain.network import RoadEdge, RoadNetwork, RoadNode
from cs_mapgen.domain.raster import DEMTile

FAKE_DEM_SIDE = 64
FAKE_DEM_NODATA = -9999.0
FAKE_RESOLUTION_METRES = 30.0
SHA256_HEX_LENGTH = 64


class FakeDEMSource:
    provider_id = "fake-dem"

    def fetch(self, bounds: GeoBounds, context: StageContext) -> DEMTile:
        del context
        elevation = np.linspace(
            0.0,
            500.0,
            FAKE_DEM_SIDE * FAKE_DEM_SIDE,
            dtype=np.float32,
        ).reshape((FAKE_DEM_SIDE, FAKE_DEM_SIDE))
        pixel_size = (bounds.east - bounds.west) / FAKE_DEM_SIDE
        transform = (
            pixel_size,
            0.0,
            bounds.west,
            0.0,
            -pixel_size,
            bounds.north,
        )
        return DEMTile(
            elevation=elevation,
            transform=transform,
            crs=Projection.wgs84(),
            nodata=FAKE_DEM_NODATA,
            provider=self.provider_id,
            resolution_metres=FAKE_RESOLUTION_METRES,
        )


class FakeOSMSource:
    def fetch_roads(
        self,
        bounds: GeoBounds,
        network_type: str,
        context: StageContext,
    ) -> RoadNetwork:
        del network_type, context
        nodes = (
            RoadNode(node_id=1, x=bounds.west, y=bounds.south),
            RoadNode(node_id=2, x=bounds.east, y=bounds.north),
        )
        edges = (
            RoadEdge(
                source=1,
                target=2,
                geometry=((bounds.west, bounds.south), (bounds.east, bounds.north)),
                highway_class="residential",
                length_metres=1000.0,
            ),
        )
        return RoadNetwork(nodes=nodes, edges=edges, crs=Projection.wgs84())


class IdentityReprojector:
    """A reprojector that returns its input unchanged. Used in fakes to skip GDAL."""

    def reproject_raster(self, tile: DEMTile, target: Projection, resampling: str) -> DEMTile:
        del resampling
        return DEMTile(
            elevation=tile.elevation,
            transform=tile.transform,
            crs=target,
            nodata=tile.nodata,
            provider=tile.provider,
            resolution_metres=tile.resolution_metres,
        )

    def reproject_network(self, network: RoadNetwork, target: Projection) -> RoadNetwork:
        return RoadNetwork(nodes=network.nodes, edges=network.edges, crs=target)


class InMemoryArtifactStore:
    """Captures writes in memory so tests can assert on bytes without touching the filesystem."""

    def __init__(self) -> None:
        self.captured: dict[str, bytes] = {}

    def write(self, name: str, payload: bytes, context: StageContext) -> ArtifactEntry:
        self.captured[name] = payload
        return ArtifactEntry(
            name=name,
            path=str(context.output_directory / name),
            sha256=hashlib.sha256(payload).hexdigest(),
            mime="application/octet-stream",
        )

    def write_intermediate(
        self,
        stage_name: str,
        artifact_name: str,
        payload: bytes,
        context: StageContext,
    ) -> ArtifactEntry:
        del stage_name
        return self.write(artifact_name, payload, context)


class FakeExportTarget:
    target_id = "fake"

    def export(
        self,
        tile: MapTile,
        store: object,
        context: StageContext,
    ) -> ExportManifest:
        del tile, store
        return ExportManifest(
            target=self.target_id,
            bounds=context.bounds,
            inputs_hash="d" * SHA256_HEX_LENGTH,
            seed=context.seed,
            artifacts=(),
            created_at_utc="2026-01-01T00:00:00+00:00",
        )
