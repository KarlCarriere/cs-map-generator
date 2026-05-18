"""Filesystem-backed artifact store. Writes bytes, computes sha256, returns an `ArtifactEntry`."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.manifest import ArtifactEntry

DEFAULT_MIME = "application/octet-stream"
INTERMEDIATES_DIRNAME = "intermediates"


class FilesystemArtifactStore:
    """Writes artifacts under a root directory. Intermediate dumps go under a sibling subdir."""

    def __init__(self, root_directory: Path) -> None:
        self._root_directory = root_directory

    def write(self, name: str, payload: bytes, context: StageContext) -> ArtifactEntry:
        target_path = context.output_directory / name
        return self._write(target_path, name, payload)

    def write_intermediate(
        self,
        stage_name: str,
        artifact_name: str,
        payload: bytes,
        context: StageContext,
    ) -> ArtifactEntry:
        if not context.dump_intermediates:
            # Honor the context flag — intermediate dumps are opt-in for performance.
            return ArtifactEntry(
                name=artifact_name,
                path="",
                sha256=hashlib.sha256(payload).hexdigest(),
                mime=_guess_mime(artifact_name),
            )
        target_path = context.output_directory / INTERMEDIATES_DIRNAME / stage_name / artifact_name
        return self._write(target_path, artifact_name, payload)

    @staticmethod
    def _write(target_path: Path, name: str, payload: bytes) -> ArtifactEntry:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        return ArtifactEntry(
            name=name,
            path=str(target_path),
            sha256=digest,
            mime=_guess_mime(name),
        )


def _guess_mime(filename: str) -> str:
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or DEFAULT_MIME
