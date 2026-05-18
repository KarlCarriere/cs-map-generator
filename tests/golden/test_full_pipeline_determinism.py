"""Golden-output determinism test.

Hashes the bytes of the exported CS1 heightmap PNG and asserts the digest is stable across
runs. This is the determinism contract. The test is marked `xfail(strict=True)` until the first
successful run records a real baseline hash — at that point the assertion flips to enforcement
and any byte-level regression breaks CI.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from cs_mapgen.application.pipeline import PipelineBuilder
from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection, pick_utm_projection
from cs_mapgen.domain.manifest import ExportManifest
from cs_mapgen.infrastructure.export import CS1ExportTarget
from tests._fakes import (
    FakeDEMSource,
    FakeOSMSource,
    IdentityReprojector,
    InMemoryArtifactStore,
)

GOLDEN_HEIGHTMAP_SHA256 = "TODO-BASELINE-FROM-FIRST-SUCCESSFUL-RUN"
GOLDEN_BBOX = GeoBounds(
    west=0.4, south=0.4, east=0.6, north=0.6, crs=Projection.wgs84()
)
GOLDEN_SEED = 12345


@pytest.mark.golden
@pytest.mark.xfail(
    reason=(
        "Baseline heightmap SHA-256 not yet recorded. On first successful run, copy the "
        "computed digest from the test failure message into GOLDEN_HEIGHTMAP_SHA256 and "
        "remove this xfail."
    ),
    strict=True,
)
def test_should_produce_byte_identical_heightmap_when_pipeline_runs_with_fixed_inputs(
    tmp_path: Path,
) -> None:
    store = InMemoryArtifactStore()
    pipeline = (
        PipelineBuilder()
        .with_dem_source(FakeDEMSource())
        .with_osm_source(FakeOSMSource())
        .with_reprojector(IdentityReprojector())
        .with_artifact_store(store)
        .with_export_target(CS1ExportTarget(reprojector=IdentityReprojector()))
        .build_terrain_and_roads()
    )
    context = StageContext(
        bounds=GOLDEN_BBOX,
        working_crs=pick_utm_projection(GOLDEN_BBOX),
        seed=GOLDEN_SEED,
        cache_directory=tmp_path / "cache",
        output_directory=tmp_path / "out",
        dump_intermediates=False,
        logger=logging.getLogger("cs_mapgen.golden"),
    )

    result = pipeline.run(initial_input=None, context=context)
    final = result.final_output
    assert isinstance(final, ExportManifest)

    heightmap_bytes = store.captured["heightmap.png"]
    actual_digest = hashlib.sha256(heightmap_bytes).hexdigest()

    assert actual_digest == GOLDEN_HEIGHTMAP_SHA256, (
        f"Determinism baseline drift. Computed digest: {actual_digest}. "
        "If this is the first successful run, copy this digest into GOLDEN_HEIGHTMAP_SHA256 "
        "and remove the @pytest.mark.xfail decorator on this test."
    )
