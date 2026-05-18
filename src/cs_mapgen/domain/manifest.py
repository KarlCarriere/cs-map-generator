"""Export manifest — the reproducibility contract."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from cs_mapgen.domain.geometry import GeoBounds

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    """One file in an export bundle."""

    name: str
    path: str
    sha256: str
    mime: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ArtifactEntry name must be non-empty")
        if len(self.sha256) != 64:
            raise ValueError(f"sha256 must be a 64-character hex digest, got {self.sha256!r}")


@dataclass(frozen=True, slots=True)
class ExportManifest:
    """The full provenance record for an export run."""

    target: str
    bounds: GeoBounds
    inputs_hash: str
    seed: int
    artifacts: tuple[ArtifactEntry, ...]
    created_at_utc: str
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def to_json(self) -> str:
        """Serialize to canonical JSON. Keys are sorted; this is part of the determinism contract."""
        payload = {
            "schema_version": self.schema_version,
            "target": self.target,
            "bounds": {
                "west": self.bounds.west,
                "south": self.bounds.south,
                "east": self.bounds.east,
                "north": self.bounds.north,
                "crs_epsg": self.bounds.crs.epsg,
            },
            "inputs_hash": self.inputs_hash,
            "seed": self.seed,
            "created_at_utc": self.created_at_utc,
            "artifacts": [asdict(entry) for entry in self.artifacts],
        }
        return json.dumps(payload, sort_keys=True, indent=2)
