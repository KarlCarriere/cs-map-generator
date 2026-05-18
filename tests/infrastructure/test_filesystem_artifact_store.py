"""Tests for the FilesystemArtifactStore."""

from __future__ import annotations

import hashlib

from cs_mapgen.application.stage import StageContext
from cs_mapgen.infrastructure.artifact_store import FilesystemArtifactStore


def test_should_write_artifact_and_return_sha256_entry_when_payload_is_given(
    stage_context: StageContext,
) -> None:
    store = FilesystemArtifactStore(root_directory=stage_context.output_directory)
    payload = b"hello world"

    entry = store.write("hello.txt", payload, stage_context)

    assert entry.name == "hello.txt"
    assert entry.sha256 == hashlib.sha256(payload).hexdigest()
    assert (stage_context.output_directory / "hello.txt").read_bytes() == payload


def test_should_skip_intermediate_when_dump_intermediates_is_false(
    stage_context: StageContext,
) -> None:
    store = FilesystemArtifactStore(root_directory=stage_context.output_directory)

    entry = store.write_intermediate("dem", "raw.hgt", b"payload", stage_context)

    assert entry.path == ""
    assert not (stage_context.output_directory / "intermediates" / "dem" / "raw.hgt").exists()
