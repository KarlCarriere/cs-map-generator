"""Ingest stage: fetch OSM water polygons, waterways, and coastlines for the bbox.

Delegates to an injected `OSMWaterSource` port. The port returns a fully-typed `WaterFeatures`
value — no raw geopandas/shapely crosses the application boundary.

Determinism: delegated to the port. `OSMnxWaterSource` content-addresses its cache by
`(bbox, osmnx_version, tag_query_hash)` and sorts every iteration that affects output ordering.
"""

from __future__ import annotations

from dataclasses import dataclass

from cs_mapgen.application.ports import OSMWaterSource
from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.ingest_roads import IngestRoadsResult
from cs_mapgen.domain.water import WaterFeatures


@dataclass(frozen=True, slots=True)
class IngestWaterResult:
    ingested_roads: IngestRoadsResult
    water_features: WaterFeatures


class IngestWaterStage:
    """Fetch water features and forward them alongside the upstream ingest results."""

    name = "ingest_water"

    def __init__(self, water_source: OSMWaterSource) -> None:
        self._water_source = water_source

    def run(self, inputs: IngestRoadsResult, context: StageContext) -> IngestWaterResult:
        features = self._water_source.fetch_water(context.bounds, context)
        context.logger.info(
            "water.ingested",
            extra={
                "polygon_count": len(features.polygons),
                "waterway_count": len(features.waterways),
                "coastline_count": len(features.coastlines),
            },
        )
        return IngestWaterResult(ingested_roads=inputs, water_features=features)
