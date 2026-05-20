"""CLI happy-path tests. The pipeline factory is monkeypatched to inject fakes.

v0.2 NOTE: the pipeline now includes `ConditionTerrainStage` (pysheds) and
`PrepareWaterStage` (rasterio). Both are part of the `gis` optional dependency group; tests
that exercise the full pipeline therefore require it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cs_mapgen import __version__
from cs_mapgen.application.pipeline import PipelineBuilder
from cs_mapgen.infrastructure.export import CS1ExportTarget
from cs_mapgen.interfaces.cli.app import app
from tests._fakes import (
    FakeDEMSource,
    FakeOSMSource,
    FakeOSMWaterSource,
    IdentityReprojector,
    InMemoryArtifactStore,
)

ARTIFACT_STORE_HOLDER: dict[str, InMemoryArtifactStore] = {}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _reset_artifact_store_holder() -> None:
    ARTIFACT_STORE_HOLDER.clear()


def _build_fake_pipeline(_settings, *, target_id):
    del target_id
    # Stash the artifact store so the equivalence test can read the captured PNG bytes.
    store = InMemoryArtifactStore()
    ARTIFACT_STORE_HOLDER["store"] = store
    return (
        PipelineBuilder()
        .with_dem_source(FakeDEMSource())
        .with_osm_source(FakeOSMSource())
        .with_water_source(FakeOSMWaterSource())
        .with_reprojector(IdentityReprojector())
        .with_artifact_store(store)
        .with_export_target(CS1ExportTarget(reprojector=IdentityReprojector()))
        .build_terrain_and_roads()
    )


def test_should_print_version_when_version_flag_is_passed(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_should_print_manifest_json_when_generate_with_bbox(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cs_mapgen.interfaces.cli.app.build_production_pipeline",
        _build_fake_pipeline,
    )

    output_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "generate",
            "--bbox",
            "0.4,0.4,0.6,0.6",
            "--target",
            "cs1",
            "--out",
            str(output_dir),
            "--seed",
            "42",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["target"] == "cs1"
    assert payload["seed"] == 42


def test_should_print_manifest_json_when_generate_with_center(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cs_mapgen.interfaces.cli.app.build_production_pipeline",
        _build_fake_pipeline,
    )

    output_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "generate",
            "--center",
            "46.81,-71.21",
            "--target",
            "cs1",
            "--out",
            str(output_dir),
            "--seed",
            "42",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["target"] == "cs1"
    assert payload["seed"] == 42


def test_should_produce_deterministic_heightmap_when_center_is_re_run_with_same_seed(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Determinism: two runs of the same --center invocation must produce byte-identical PNGs.

    v0.2 NOTE: previously this test asserted equivalence between --center and the
    `resolved` --bbox derived from it. That equivalence no longer holds because
    `resolve_extent` now produces an exact metric square in working_crs for --center while
    --bbox is interpreted as a WGS84 fetch envelope (with an inscribed UTM rectangle as the
    target). The two paths intentionally model different user intents; we keep the
    determinism contract by re-running the same shape twice instead.
    """
    monkeypatch.setattr(
        "cs_mapgen.interfaces.cli.app.build_production_pipeline",
        _build_fake_pipeline,
    )

    center_lat = 46.81
    center_lon = -71.21
    radius_tiles = 4
    target = "cs1"

    args = [
        "generate",
        "--center",
        f"{center_lat},{center_lon}",
        "--radius-tiles",
        str(radius_tiles),
        "--target",
        target,
        "--seed",
        "7",
    ]

    first = runner.invoke(app, [*args, "--out", str(tmp_path / "first")])
    assert first.exit_code == 0, first.stdout
    first_png = ARTIFACT_STORE_HOLDER["store"].captured["heightmap.png"]

    second = runner.invoke(app, [*args, "--out", str(tmp_path / "second")])
    assert second.exit_code == 0, second.stdout
    second_png = ARTIFACT_STORE_HOLDER["store"].captured["heightmap.png"]

    assert hashlib.sha256(first_png).hexdigest() == hashlib.sha256(second_png).hexdigest()


def test_should_exit_with_usage_error_when_center_and_bbox_are_both_passed(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cs_mapgen.interfaces.cli.app.build_production_pipeline",
        _build_fake_pipeline,
    )

    result = runner.invoke(
        app,
        [
            "generate",
            "--center",
            "46.81,-71.21",
            "--bbox",
            "0.4,0.4,0.6,0.6",
            "--target",
            "cs1",
            "--out",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code != 0
    combined_output = (result.stdout + result.stderr).lower()
    assert "--center" in combined_output
    assert "--bbox" in combined_output


def test_should_exit_with_usage_error_when_neither_center_nor_bbox_is_passed(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cs_mapgen.interfaces.cli.app.build_production_pipeline",
        _build_fake_pipeline,
    )

    result = runner.invoke(
        app,
        [
            "generate",
            "--target",
            "cs1",
            "--out",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code != 0
