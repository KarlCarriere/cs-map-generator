"""FastAPI happy-path tests using the in-process ASGI transport."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from cs_mapgen import __version__
from cs_mapgen.application.pipeline import PipelineBuilder
from cs_mapgen.config.settings import Settings
from cs_mapgen.infrastructure.export import CS1ExportTarget
from cs_mapgen.interfaces.http.app import create_app
from cs_mapgen.interfaces.http.dependencies import get_pipeline_factory, get_settings
from tests._fakes import (
    FakeDEMSource,
    FakeOSMSource,
    IdentityReprojector,
    InMemoryArtifactStore,
)


@pytest.fixture
def test_app(tmp_path: Path):
    app = create_app()

    def _build_fake_pipeline(_settings, _target_id):
        return (
            PipelineBuilder()
            .with_dem_source(FakeDEMSource())
            .with_osm_source(FakeOSMSource())
            .with_reprojector(IdentityReprojector())
            .with_artifact_store(InMemoryArtifactStore())
            .with_export_target(CS1ExportTarget(reprojector=IdentityReprojector()))
            .build_terrain_and_roads()
        )

    test_settings = Settings(
        cache_directory=tmp_path / "cache",
        output_directory=tmp_path / "out",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_pipeline_factory] = lambda: _build_fake_pipeline
    return app


async def test_should_report_ok_when_health_endpoint_is_called(test_app) -> None:
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_should_return_manifest_when_maps_called_with_bbox_input(test_app) -> None:
    payload = {
        "input": {
            "kind": "bbox",
            "west": 0.4,
            "south": 0.4,
            "east": 0.6,
            "north": 0.6,
        },
        "target": "cs1",
        "seed": 7,
        "dump_intermediates": False,
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post("/maps", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target"] == "cs1"
    assert body["seed"] == 7
    assert len(body["artifacts"]) >= 1


async def test_should_return_manifest_when_maps_called_with_center_input(test_app) -> None:
    payload = {
        "input": {
            "kind": "center",
            "lat": 46.81,
            "lon": -71.21,
        },
        "target": "cs1",
        "seed": 7,
        "dump_intermediates": False,
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post("/maps", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target"] == "cs1"
    assert body["seed"] == 7
    assert len(body["artifacts"]) >= 1


async def test_should_return_manifest_when_maps_called_with_center_input_explicit_radius(
    test_app,
) -> None:
    payload = {
        "input": {
            "kind": "center",
            "lat": 46.81,
            "lon": -71.21,
            "radius_tiles": 4,
        },
        "target": "cs1",
        "seed": 7,
        "dump_intermediates": False,
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post("/maps", json=payload)

    assert response.status_code == 201, response.text


async def test_should_return_400_when_bbox_is_invalid(test_app) -> None:
    payload = {
        "input": {
            "kind": "bbox",
            "west": 0.6,
            "south": 0.4,
            "east": 0.4,  # east < west — invalid
            "north": 0.6,
        },
        "target": "cs1",
        "seed": 0,
        "dump_intermediates": False,
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post("/maps", json=payload)

    assert response.status_code == 400


async def test_should_return_422_when_payload_mixes_center_and_bbox_fields(test_app) -> None:
    # Malformed: `kind` is "center" but the body also carries bbox keys. The CenterInput
    # schema has `extra="forbid"`, so Pydantic rejects the extra fields with a 422.
    payload = {
        "input": {
            "kind": "center",
            "lat": 46.81,
            "lon": -71.21,
            "west": 0.4,
            "south": 0.4,
            "east": 0.6,
            "north": 0.6,
        },
        "target": "cs1",
        "seed": 0,
        "dump_intermediates": False,
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post("/maps", json=payload)

    assert response.status_code == 422, response.text


async def test_should_return_422_when_input_kind_is_unknown(test_app) -> None:
    payload = {
        "input": {
            "kind": "not-a-real-kind",
            "lat": 46.81,
            "lon": -71.21,
        },
        "target": "cs1",
        "seed": 0,
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post("/maps", json=payload)

    assert response.status_code == 422
