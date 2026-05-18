"""Port Protocols — the infrastructure boundary."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.manifest import ArtifactEntry, ExportManifest
from cs_mapgen.domain.map_tile import MapTile
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.raster import DEMTile


@runtime_checkable
class DEMSource(Protocol):
    """Fetches DEM tiles covering a bounding box."""

    provider_id: str

    def fetch(self, bounds: GeoBounds, context: StageContext) -> DEMTile: ...


@runtime_checkable
class OSMSource(Protocol):
    """Fetches OSM-derived data for a bounding box."""

    def fetch_roads(
        self,
        bounds: GeoBounds,
        network_type: str,
        context: StageContext,
    ) -> RoadNetwork: ...


@runtime_checkable
class Reprojector(Protocol):
    """Reprojects rasters and vectors between coordinate systems."""

    def reproject_raster(
        self,
        tile: DEMTile,
        target: Projection,
        resampling: str,
    ) -> DEMTile: ...

    def reproject_network(
        self,
        network: RoadNetwork,
        target: Projection,
    ) -> RoadNetwork: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Writes intermediate and final artifacts to durable storage."""

    def write(self, name: str, payload: bytes, context: StageContext) -> ArtifactEntry: ...

    def write_intermediate(
        self,
        stage_name: str,
        artifact_name: str,
        payload: bytes,
        context: StageContext,
    ) -> ArtifactEntry: ...


@runtime_checkable
class ExportTarget(Protocol):
    """Serializes a composed MapTile into engine-specific artifacts."""

    target_id: str

    def export(
        self,
        tile: MapTile,
        store: ArtifactStore,
        context: StageContext,
    ) -> ExportManifest: ...
