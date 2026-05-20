"""Golden-output determinism test.

Hashes the bytes of the exported CS1 `heightmap.png`, `water_mask.png`, and `manifest.json`
and asserts every digest is stable across runs. This is the determinism contract. The test is
marked `xfail(strict=True)` until the first successful run records real baseline hashes — at
that point the assertions flip to enforcement and any byte-level regression breaks CI.

v0.2 (`feat/v0.2-water`): the fixture exercises the full pit-fill + water-carve + water-mask
pipeline. The baselines below need to be recorded by running the test once and copying the
reported digests into `GOLDEN_HEIGHTMAP_SHA256`, `GOLDEN_WATER_MASK_SHA256`, and
`GOLDEN_MANIFEST_SHA256`.

To regenerate baselines:

    uv run pytest tests/golden/test_full_pipeline_determinism.py -m golden -s

The test failure message prints all three digests; copy them into the constants and remove the
`@pytest.mark.xfail` decorator.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from cs_mapgen.application.pipeline import PipelineBuilder
from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.manifest import ExportManifest
from cs_mapgen.domain.water import WaterFeatures, WaterPolygon, Waterway
from cs_mapgen.infrastructure.export import CS1ExportTarget
from tests._fakes import (
    FakeDEMSource,
    FakeOSMSource,
    FakeOSMWaterSource,
    IdentityReprojector,
    InMemoryArtifactStore,
)

GOLDEN_HEIGHTMAP_SHA256 = "TODO-BASELINE-FROM-FIRST-SUCCESSFUL-RUN"
GOLDEN_WATER_MASK_SHA256 = "TODO-BASELINE-FROM-FIRST-SUCCESSFUL-RUN"
GOLDEN_MANIFEST_SHA256 = "TODO-BASELINE-FROM-FIRST-SUCCESSFUL-RUN"
GOLDEN_BBOX = GeoBounds(west=0.4, south=0.4, east=0.6, north=0.6, crs=Projection.wgs84())
GOLDEN_SEED = 12345


def _golden_water_features() -> WaterFeatures:
    """A small, hand-crafted offline water fixture committed to the test source.

    The geometry is in WGS84 lon/lat (the OSMnx adapter's native CRS), inside `GOLDEN_BBOX`.
    One small polygon, one short waterway, zero coastlines — enough to exercise both the
    polygon-rasterise and waterway-buffer code paths without bringing in coastline reconstruction
    which is tested separately.
    """
    polygon = WaterPolygon(
        exterior=(
            (0.48, 0.48),
            (0.52, 0.48),
            (0.52, 0.52),
            (0.48, 0.52),
            (0.48, 0.48),
        ),
    )
    waterway = Waterway(
        geometry=((0.41, 0.45), (0.45, 0.49), (0.49, 0.55)),
        waterway_class="river",
    )
    return WaterFeatures(
        polygons=(polygon,),
        waterways=(waterway,),
        coastlines=(),
        crs=Projection.wgs84(),
    )


@pytest.mark.golden
@pytest.mark.xfail(
    reason=(
        "Baseline digests not yet recorded for v0.2. On first successful run, copy the "
        "three computed digests from the test failure message into "
        "GOLDEN_HEIGHTMAP_SHA256 / GOLDEN_WATER_MASK_SHA256 / GOLDEN_MANIFEST_SHA256 and "
        "remove this xfail."
    ),
    strict=True,
)
def test_should_produce_byte_identical_artifacts_when_pipeline_runs_with_fixed_inputs(
    tmp_path: Path,
) -> None:
    store = InMemoryArtifactStore()
    pipeline = (
        PipelineBuilder()
        .with_dem_source(FakeDEMSource())
        .with_osm_source(FakeOSMSource())
        .with_water_source(FakeOSMWaterSource(features=_golden_water_features()))
        .with_reprojector(IdentityReprojector())
        .with_artifact_store(store)
        .with_export_target(CS1ExportTarget(reprojector=IdentityReprojector()))
        .build_terrain_and_roads()
    )
    context = StageContext(
        bounds=GOLDEN_BBOX,
        target_bounds=GOLDEN_BBOX,
        playable_bounds=GOLDEN_BBOX,
        working_crs=Projection.wgs84(),
        seed=GOLDEN_SEED,
        cache_directory=tmp_path / "cache",
        output_directory=tmp_path / "out",
        dump_intermediates=False,
        logger=logging.getLogger("cs_mapgen.golden"),
    )

    result = pipeline.run(initial_input=None, context=context)
    final = result.final_output
    assert isinstance(final, ExportManifest)

    heightmap_digest = hashlib.sha256(store.captured["heightmap.png"]).hexdigest()
    water_mask_digest = hashlib.sha256(store.captured["water_mask.png"]).hexdigest()
    manifest_digest = hashlib.sha256(store.captured["manifest.json"]).hexdigest()

    assert (
        heightmap_digest == GOLDEN_HEIGHTMAP_SHA256
        and water_mask_digest == GOLDEN_WATER_MASK_SHA256
        and manifest_digest == GOLDEN_MANIFEST_SHA256
    ), (
        "Determinism baseline drift (v0.2). Computed digests:\n"
        f"  heightmap.png:  {heightmap_digest}\n"
        f"  water_mask.png: {water_mask_digest}\n"
        f"  manifest.json:  {manifest_digest}\n"
        "If this is the first successful v0.2 run, copy these digests into "
        "GOLDEN_HEIGHTMAP_SHA256 / GOLDEN_WATER_MASK_SHA256 / GOLDEN_MANIFEST_SHA256 "
        "and remove the @pytest.mark.xfail decorator on this test."
    )
