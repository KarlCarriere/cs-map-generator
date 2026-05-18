"""Ingest stage: fetch a DEM tile covering the bbox."""

from __future__ import annotations

from dataclasses import dataclass

from cs_mapgen.application.ports import DEMSource
from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.raster import DEMTile


@dataclass(frozen=True, slots=True)
class IngestDEMResult:
    dem_tile: DEMTile


class IngestDEMStage:
    """Delegates DEM acquisition to an injected `DEMSource` port.

    The stage is intentionally thin: validation, caching, and retry logic live inside the port
    implementation. Determinism is delegated to the port — `SRTMDEMSource` guarantees that a
    given bbox always yields the same tile bytes via content-addressed caching.
    """

    name = "ingest_dem"

    def __init__(self, dem_source: DEMSource) -> None:
        self._dem_source = dem_source

    def run(self, inputs: object, context: StageContext) -> IngestDEMResult:
        del inputs  # The first stage receives the initial input from the orchestrator.
        tile = self._dem_source.fetch(context.bounds, context)
        return IngestDEMResult(dem_tile=tile)
