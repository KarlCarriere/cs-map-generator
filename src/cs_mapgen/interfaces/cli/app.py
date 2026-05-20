"""Typer-based CLI. Translates argv into a `Pipeline.run` call. No business logic.

The CLI accepts the map extent in two equivalent shapes (exactly one must be passed):

- `--center LAT,LON [--radius-tiles N]`: natural Cities: Skylines UX. The centre tile sits at
  the given coordinate and the playable area extends `N` tiles in every cardinal direction. The
  default `N` depends on the chosen `--target` (CS1 → 4, CS2 → 10), matching each game's full
  tile-grid. Note the lat-first order — it matches the human-natural "latitude, longitude"
  convention.

- `--bbox W,S,E,N`: power-user / scripting path. Order is lon-first to match the W/S/E/N
  geographic convention.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from cs_mapgen import __version__
from cs_mapgen.application.extent_resolver import (
    ExtentResolutionError,
    ResolvedExtent,
    resolve_extent,
)
from cs_mapgen.application.pipeline import Pipeline, PipelineResult
from cs_mapgen.application.stage import StageContext
from cs_mapgen.config.settings import Settings, load_settings
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
from cs_mapgen.interfaces.composition import TARGET_REGISTRY, build_production_pipeline

WGS84_EPSG = 4326
BBOX_PIECE_COUNT = 4
CENTER_PIECE_COUNT = 2

app = typer.Typer(
    name="cs-mapgen",
    help="Real-world coordinate -> Cities: Skylines 1 / 2 map artifacts.",
    add_completion=False,
    no_args_is_help=True,
)


def _print_version_and_exit(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(code=0)


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print version and exit.",
            is_eager=True,
            callback=_print_version_and_exit,
        ),
    ] = False,
) -> None:
    del version  # handled by the eager callback above


@app.command()
def generate(
    target: Annotated[
        str,
        typer.Option("--target", help=f"Export target. One of: {sorted(TARGET_REGISTRY)}."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Output directory for artifacts."),
    ],
    center: Annotated[
        str | None,
        typer.Option(
            "--center",
            help=(
                "Centre coordinate as 'LAT,LON' in WGS84 decimal degrees "
                "(natural human order: latitude first). Mutually exclusive with --bbox."
            ),
        ),
    ] = None,
    radius_tiles: Annotated[
        int | None,
        typer.Option(
            "--radius-tiles",
            help=(
                "Number of game tiles in each cardinal direction around --center. "
                "Defaults to the full game-standard radius for --target (CS1: 4, CS2: 10)."
            ),
        ),
    ] = None,
    bbox: Annotated[
        str | None,
        typer.Option(
            "--bbox",
            help=(
                "Bounding box as 'west,south,east,north' in WGS84 lon/lat degrees "
                "(lon-first, matching W/S/E/N geographic order). "
                "Mutually exclusive with --center."
            ),
        ),
    ] = None,
    seed: Annotated[
        int,
        typer.Option("--seed", help="Deterministic seed for all RNGs in the pipeline."),
    ] = 0,
    dump_intermediates: Annotated[
        bool,
        typer.Option(
            "--dump-intermediates",
            help="Write each stage's intermediate artifact for inspection.",
        ),
    ] = False,
    no_progress: Annotated[
        bool,
        typer.Option(
            "--no-progress",
            help="Disable the per-stage progress bar (auto-disabled when stderr is not a TTY).",
        ),
    ] = False,
) -> None:
    settings = load_settings()
    extent = _parse_extent(center=center, radius_tiles=radius_tiles, bbox=bbox, target=target)
    resolved = _resolve_or_fail(extent)
    pipeline = build_production_pipeline(settings, target_id=target)
    context = _make_context(settings, resolved, seed, out, dump_intermediates)
    result = _run_pipeline(pipeline, context, show_progress=not no_progress)
    manifest = _extract_manifest(result)
    typer.echo(manifest.to_json())


@app.command()
def inspect(
    artifact: Annotated[Path, typer.Argument(help="Path to a manifest.json or PNG artifact.")],
) -> None:
    """Print a short summary of a previously generated artifact or manifest."""
    if not artifact.exists():
        raise typer.BadParameter(f"Artifact does not exist: {artifact}")
    if artifact.suffix == ".json":
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"{artifact}: {artifact.stat().st_size} bytes")


def _parse_extent(
    *,
    center: str | None,
    radius_tiles: int | None,
    bbox: str | None,
    target: str,
) -> MapExtent:
    # Mutual exclusion: enforced here rather than via Typer's option groups because Typer's
    # support for mutually-exclusive options is awkward and the error message we produce here
    # mentions both flags explicitly, which is what the user wants to see.
    if center is None and bbox is None:
        raise typer.BadParameter("Provide exactly one of --center or --bbox (got neither).")
    if center is not None and bbox is not None:
        raise typer.BadParameter("--center and --bbox are mutually exclusive (got both). Pick one.")

    if bbox is not None:
        if radius_tiles is not None:
            raise typer.BadParameter(
                "--radius-tiles only applies to --center; remove it when using --bbox."
            )
        return BoundsExtent(bounds=_parse_bbox(bbox))

    return _build_center_extent(center=center, radius_tiles=radius_tiles, target=target)


def _build_center_extent(
    *,
    center: str | None,
    radius_tiles: int | None,
    target: str,
) -> CenterExtent:
    assert center is not None
    point = _parse_center(center)
    effective_radius = _resolve_default_radius(radius_tiles=radius_tiles, target=target)
    try:
        return CenterExtent(
            center=point,
            radius_tiles=effective_radius,
            target_id=target,
        )
    except InvalidExtentError as error:
        raise typer.BadParameter(str(error)) from error


def _resolve_default_radius(*, radius_tiles: int | None, target: str) -> int:
    if radius_tiles is None:
        try:
            spec = get_target_spec(target)
        except UnknownTargetError as error:
            raise typer.BadParameter(str(error)) from error
        return spec.default_radius_tiles
    if radius_tiles < 0:
        raise typer.BadParameter(
            f"--radius-tiles must be a non-negative integer, got {radius_tiles}"
        )
    return radius_tiles


def _parse_bbox(raw: str) -> GeoBounds:
    parts = [piece.strip() for piece in raw.split(",")]
    if len(parts) != BBOX_PIECE_COUNT:
        raise typer.BadParameter(
            "Expected --bbox as 'west,south,east,north' (4 comma-separated floats)."
        )
    try:
        west, south, east, north = (float(piece) for piece in parts)
    except ValueError as error:
        raise typer.BadParameter(f"Could not parse bbox floats: {error}") from error
    try:
        return GeoBounds(
            west=west,
            south=south,
            east=east,
            north=north,
            crs=Projection.wgs84(),
        )
    except InvalidBoundsError as error:
        raise typer.BadParameter(str(error)) from error


def _parse_center(raw: str) -> GeoPoint:
    parts = [piece.strip() for piece in raw.split(",")]
    if len(parts) != CENTER_PIECE_COUNT:
        raise typer.BadParameter(
            "Expected --center as 'LAT,LON' (2 comma-separated floats, latitude first)."
        )
    try:
        latitude, longitude = (float(piece) for piece in parts)
    except ValueError as error:
        raise typer.BadParameter(f"Could not parse center floats: {error}") from error
    try:
        return GeoPoint(longitude=longitude, latitude=latitude)
    except InvalidExtentError as error:
        raise typer.BadParameter(str(error)) from error


def _resolve_or_fail(extent: MapExtent) -> ResolvedExtent:
    try:
        return resolve_extent(extent)
    except ExtentResolutionError as error:
        raise typer.BadParameter(str(error)) from error


def _make_context(
    settings: Settings,
    resolved: ResolvedExtent,
    seed: int,
    output_directory: Path,
    dump_intermediates: bool,
) -> StageContext:
    output_directory.mkdir(parents=True, exist_ok=True)
    return StageContext(
        bounds=resolved.fetch_bounds,
        target_bounds=resolved.target_bounds,
        playable_bounds=resolved.playable_bounds,
        working_crs=resolved.working_crs,
        seed=seed,
        cache_directory=settings.cache_directory,
        output_directory=output_directory,
        dump_intermediates=dump_intermediates,
        logger=logging.getLogger("cs_mapgen.cli"),
    )


def _run_pipeline(
    pipeline: Pipeline,
    context: StageContext,
    *,
    show_progress: bool,
) -> PipelineResult:
    if not show_progress:
        return pipeline.run(initial_input=None, context=context)

    # Rich Progress on stderr keeps stdout reserved for the JSON manifest. `disable` is set when
    # stderr is not a TTY (e.g. piped, CI, captured by tests) so we never spam control codes into
    # a log file.
    from rich.console import Console  # noqa: PLC0415 — UI dep only used in the CLI path
    from rich.progress import (  # noqa: PLC0415
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    console = Console(stderr=True)
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total} stages"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        disable=not console.is_terminal,
    )

    with progress:
        task_id = progress.add_task("Initialising…", total=len(pipeline.stages))

        def _on_start(stage_name: str, index: int, total: int) -> None:
            del total
            progress.update(task_id, description=f"[{index + 1}] {stage_name}")

        def _on_end(stage_name: str, index: int, total: int) -> None:
            del stage_name, index, total
            progress.advance(task_id)

        return pipeline.run(
            initial_input=None,
            context=context,
            on_stage_start=_on_start,
            on_stage_end=_on_end,
        )


def _extract_manifest(result: PipelineResult) -> ExportManifest:
    final = result.final_output
    if not isinstance(final, ExportManifest):
        raise RuntimeError(
            f"Pipeline final output was not an ExportManifest (got {type(final).__name__})"
        )
    return final


def main() -> None:
    app()


if __name__ == "__main__":
    main()
