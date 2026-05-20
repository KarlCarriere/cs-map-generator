"""Port Protocols — the infrastructure boundary."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.manifest import ArtifactEntry, ExportManifest
from cs_mapgen.domain.map_tile import MapTile
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.raster import DEMTile
from cs_mapgen.domain.water import WaterFeatures


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
class OSMWaterSource(Protocol):
    """Fetches OSM-derived water features for a bounding box.

    The port returns ready-to-rasterise domain primitives (`WaterFeatures`) rather than raw OSM
    elements, geopandas dataframes, or shapely geometries. Rationale:

    - The application layer must not depend on shapely/geopandas — those imports stay in
      `infrastructure/osm/`. Returning `WaterFeatures` (plain tuples + numpy-free) keeps the
      port boundary framework-clean.
    - Stage tests can construct hand-crafted `WaterFeatures` directly without monkeypatching
      geopandas or pinning a fixture GeoDataFrame.
    - Adapters are free to choose their fetch + tag-filter strategy (Overpass, pyrosm, OSMnx
      `features_from_bbox`) without touching the stage code.
    """

    def fetch_water(
        self,
        bounds: GeoBounds,
        context: StageContext,
    ) -> WaterFeatures: ...


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

    def reproject_water_features(
        self,
        features: WaterFeatures,
        target: Projection,
    ) -> WaterFeatures: ...


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
