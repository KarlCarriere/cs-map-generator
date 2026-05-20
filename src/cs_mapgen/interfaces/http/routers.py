"""HTTP routers. Translate request -> Pipeline -> response. No business logic."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from cs_mapgen import __version__
from cs_mapgen.application.extent_resolver import (
    ExtentResolutionError,
    ResolvedExtent,
    resolve_extent,
)
from cs_mapgen.application.pipeline import Pipeline
from cs_mapgen.application.stage import StageContext
from cs_mapgen.config.settings import Settings
from cs_mapgen.domain.extent import (
    BoundsExtent,
    CenterExtent,
    GeoPoint,
    InvalidExtentError,
    MapExtent,
)
from cs_mapgen.domain.geometry import GeoBounds, InvalidBoundsError, Projection
from cs_mapgen.domain.manifest import ExportManifest
from cs_mapgen.domain.target_specs import UnknownTargetError, get_target_spec
from cs_mapgen.interfaces.http.dependencies import (
    get_pipeline_factory,
    get_settings,
)
from cs_mapgen.interfaces.http.schemas import (
    ArtifactResponse,
    BboxInput,
    CenterInput,
    GenerateMapRequest,
    GenerateMapResponse,
    HealthResponse,
)

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.post(
    "/maps",
    response_model=GenerateMapResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["maps"],
)
async def create_map(
    payload: GenerateMapRequest,
    settings: Settings = Depends(get_settings),
    pipeline_factory=Depends(get_pipeline_factory),
) -> GenerateMapResponse:
    extent = _build_extent(payload)
    resolved = _resolve_or_400(extent)
    context = _make_context(settings, resolved, payload)
    pipeline: Pipeline = pipeline_factory(settings, payload.target)
    result = pipeline.run(initial_input=None, context=context)
    manifest = _extract_manifest(result.final_output)
    return _manifest_to_response(manifest)


def _build_extent(payload: GenerateMapRequest) -> MapExtent:
    input_model = payload.input
    if isinstance(input_model, BboxInput):
        return BoundsExtent(bounds=_bounds_from_bbox_input(input_model))
    if isinstance(input_model, CenterInput):
        return _center_extent_from_input(input_model, target=payload.target)
    # The discriminated union narrows this in practice — keep the guard for safety.
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported input shape: {type(input_model).__name__}",
    )


def _bounds_from_bbox_input(input_model: BboxInput) -> GeoBounds:
    try:
        return GeoBounds(
            west=input_model.west,
            south=input_model.south,
            east=input_model.east,
            north=input_model.north,
            crs=Projection.wgs84(),
        )
    except InvalidBoundsError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


def _center_extent_from_input(input_model: CenterInput, *, target: str) -> CenterExtent:
    try:
        spec = get_target_spec(target)
    except UnknownTargetError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    effective_radius = (
        input_model.radius_tiles
        if input_model.radius_tiles is not None
        else spec.default_radius_tiles
    )
    try:
        point = GeoPoint(longitude=input_model.lon, latitude=input_model.lat)
        return CenterExtent(
            center=point,
            radius_tiles=effective_radius,
            target_id=target,
        )
    except InvalidExtentError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


def _resolve_or_400(extent: MapExtent) -> ResolvedExtent:
    try:
        return resolve_extent(extent)
    except ExtentResolutionError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


def _make_context(
    settings: Settings,
    resolved: ResolvedExtent,
    payload: GenerateMapRequest,
) -> StageContext:
    output_directory = Path(settings.output_directory) / f"job-seed-{payload.seed}"
    output_directory.mkdir(parents=True, exist_ok=True)
    return StageContext(
        bounds=resolved.fetch_bounds,
        target_bounds=resolved.target_bounds,
        playable_bounds=resolved.playable_bounds,
        working_crs=resolved.working_crs,
        seed=payload.seed,
        cache_directory=settings.cache_directory,
        output_directory=output_directory,
        dump_intermediates=payload.dump_intermediates,
        logger=logging.getLogger("cs_mapgen.http"),
    )


def _extract_manifest(value: object) -> ExportManifest:
    if not isinstance(value, ExportManifest):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline produced unexpected type {type(value).__name__}",
        )
    return value


def _manifest_to_response(manifest: ExportManifest) -> GenerateMapResponse:
    return GenerateMapResponse(
        target=manifest.target,
        inputs_hash=manifest.inputs_hash,
        seed=manifest.seed,
        created_at_utc=manifest.created_at_utc,
        artifacts=[
            ArtifactResponse(name=entry.name, path=entry.path, sha256=entry.sha256, mime=entry.mime)
            for entry in manifest.artifacts
        ],
    )
