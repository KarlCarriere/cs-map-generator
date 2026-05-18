"""Domain layer — pure value objects, zero framework dependencies."""

from cs_mapgen.domain.extent import (
    BoundsExtent,
    CenterExtent,
    GeoPoint,
    InvalidExtentError,
    MapExtent,
)
from cs_mapgen.domain.geometry import GeoBounds, InvalidBoundsError, Projection
from cs_mapgen.domain.manifest import ArtifactEntry, ExportManifest
from cs_mapgen.domain.map_tile import MapTile
from cs_mapgen.domain.network import RoadEdge, RoadNetwork, RoadNode
from cs_mapgen.domain.raster import DEMTile, Heightmap, LandUseMap, VegetationMask, WaterMask
from cs_mapgen.domain.target_specs import (
    TargetSpec,
    UnknownTargetError,
    get_target_spec,
    registered_target_ids,
)

__all__ = [
    "ArtifactEntry",
    "BoundsExtent",
    "CenterExtent",
    "DEMTile",
    "ExportManifest",
    "GeoBounds",
    "GeoPoint",
    "Heightmap",
    "InvalidBoundsError",
    "InvalidExtentError",
    "LandUseMap",
    "MapExtent",
    "MapTile",
    "Projection",
    "RoadEdge",
    "RoadNetwork",
    "RoadNode",
    "TargetSpec",
    "UnknownTargetError",
    "VegetationMask",
    "WaterMask",
    "get_target_spec",
    "registered_target_ids",
]
