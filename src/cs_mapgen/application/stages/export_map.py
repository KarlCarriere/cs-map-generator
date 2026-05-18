"""Export stage: serialize the composed MapTile via the target adapter."""

from __future__ import annotations

from cs_mapgen.application.ports import ArtifactStore, ExportTarget
from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.manifest import ExportManifest
from cs_mapgen.domain.map_tile import MapTile


class ExportMapStage:
    """Hand the composed tile to the export target. Pure orchestration; no per-pixel logic."""

    name = "export_map"

    def __init__(self, target: ExportTarget, store: ArtifactStore) -> None:
        self._target = target
        self._store = store

    def run(self, inputs: MapTile, context: StageContext) -> ExportManifest:
        return self._target.export(inputs, self._store, context)
