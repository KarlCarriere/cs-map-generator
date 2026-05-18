"""CLI happy-path tests. The pipeline factory is monkeypatched to inject fakes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cs_mapgen import __version__
from cs_mapgen.application.extent_resolver import resolve_extent
from cs_mapgen.application.pipeline import PipelineBuilder
from cs_mapgen.domain.extent import CenterExtent, GeoPoint
from cs_mapgen.infrastructure.export import CS1ExportTarget
from cs_mapgen.interfaces.cli.app import app
from tests._fakes import (
    FakeDEMSource,
    FakeOSMSource,
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


def _build_fake_pipeline(_settings, *, target_id):  # noqa: ARG001 — signature must mirror production
    del target_id
    # Stash the artifact store so the equivalence test can read the captured PNG bytes.
    store = InMemoryArtifactStore()
    ARTIFACT_STORE_HOLDER["store"] = store
    return (
        PipelineBuilder()
        .with_dem_source(FakeDEMSource())
        .with_osm_source(FakeOSMSource())
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


def test_should_produce_identical_heightmap_when_center_and_equivalent_bbox_are_used(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Determinism equivalence: --center and the equivalent --bbox must produce the same PNG.

    This is the contract guaranteed by ADR 0003: the pipeline still consumes a `GeoBounds`, so
    when the resolved `GeoBounds` from `--center` exactly equals the explicit `--bbox`, the
    output bytes must match.
    """
    monkeypatch.setattr(
        "cs_mapgen.interfaces.cli.app.build_production_pipeline",
        _build_fake_pipeline,
    )

    center_lat = 46.81
    center_lon = -71.21
    radius_tiles = 4
    target = "cs1"

    extent = CenterExtent(
        center=GeoPoint(longitude=center_lon, latitude=center_lat),
        radius_tiles=radius_tiles,
        target_id=target,
    )
    equivalent_bounds = resolve_extent(extent)

    result_center = runner.invoke(
        app,
        [
            "generate",
            "--center",
            f"{center_lat},{center_lon}",
            "--radius-tiles",
            str(radius_tiles),
            "--target",
            target,
            "--out",
            str(tmp_path / "center-out"),
            "--seed",
            "7",
        ],
    )
    assert result_center.exit_code == 0, result_center.stdout
    center_png = ARTIFACT_STORE_HOLDER["store"].captured["heightmap.png"]

    bbox_string = (
        f"{equivalent_bounds.west},{equivalent_bounds.south},"
        f"{equivalent_bounds.east},{equivalent_bounds.north}"
    )
    result_bbox = runner.invoke(
        app,
        [
            "generate",
            "--bbox",
            bbox_string,
            "--target",
            target,
            "--out",
            str(tmp_path / "bbox-out"),
            "--seed",
            "7",
        ],
    )
    assert result_bbox.exit_code == 0, result_bbox.stdout
    bbox_png = ARTIFACT_STORE_HOLDER["store"].captured["heightmap.png"]

    assert hashlib.sha256(center_png).hexdigest() == hashlib.sha256(bbox_png).hexdigest()


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
