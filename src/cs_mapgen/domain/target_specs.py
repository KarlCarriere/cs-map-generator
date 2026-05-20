"""Per-game tile geometry — the single source of truth for the tile grid.

This module is a small registry mapping a `target_id` (e.g. `"cs1"`, `"cs2"`) to the per-game
tile metrics: the side length of one in-game tile in metres, the full square grid dimension
(e.g. 9 for CS1, 21 for CS2), and the default radius in tiles used when the user does not pin
one explicitly on the `--center` / center-input request.

Why this lives in the domain rather than `config/` or `infrastructure/`:
- These numbers are an intrinsic property of the target game's map structure, not deployment
  config. They never come from the environment.
- Both the domain extent resolver and the export target adapters read from them; placing them
  in a higher layer would force one of those layers to depend on a layer it should not.
- Pure data, no framework dependencies — fits the domain's contract.

Sources (see `docs/adr/0003-center-coordinate-input.md`):
- CS1: 9 × 9 grid, 17.28 km map side, therefore per-tile side = 1920 m. Documented widely on
  the Paradox wiki and Skylines modding community references.
- CS2: 21 × 21 grid totalling 441 tiles. Per-tile side is community-measured at ≈ 623.3 m
  (Paradox publicly rounded this to 600 m). We pin the community measurement and mark the
  value for re-verification once Colossal Order publishes an authoritative number.
"""

from __future__ import annotations

from dataclasses import dataclass

CS1_TARGET_ID = "cs1"
CS2_TARGET_ID = "cs2"

CS1_TILE_SIDE_METRES = 1920.0
CS1_GRID_DIMENSION = 9
CS1_DEFAULT_RADIUS_TILES = 4

# CS2 playable area side length, per the Paradox dev diaries and cs2.paradoxwikis.com/Map_Creation
# ("the heightmap PNG represents 14,336 m × 14,336 m"). Earlier versions of this module used a
# community-measured per-tile value of 623.3 m; the wiki figure of 14,336 m total is the
# authoritative one and produces a per-tile side of 14,336 / 21 ≈ 682.67 m. The community number
# appears to have measured the navigable / build-zone area rather than the heightmap-stretched
# extent that CS2 actually applies on import. Updated when the CS2 heightmap import was observed
# to leave a ~10% green border on the rendered area at 623.3 m.
CS2_PLAYABLE_SIDE_METRES = 14336.0
CS2_GRID_DIMENSION = 21
CS2_TILE_SIDE_METRES = CS2_PLAYABLE_SIDE_METRES / CS2_GRID_DIMENSION
CS2_DEFAULT_RADIUS_TILES = 10

# CS2 carries a separate `worldmap.png` showing the surroundings beyond the playable area. The
# worldmap is 4096 × 4096 pixels with the playable area mapped to the center 1024 × 1024 region
# (Paradox dev diaries + ADR 0002). The 4× pixel ratio at the same metres-per-pixel scale means
# the worldmap covers 4× the playable area in linear extent → 16× in area. We carry this as a
# `render_extent_multiplier` on the target spec so the pipeline fetches DEM/OSM over the full
# worldmap extent and the export adapter can produce both heightmap.png and worldmap.png from a
# single rendered terrain.
CS1_RENDER_EXTENT_MULTIPLIER = 1.0
CS2_RENDER_EXTENT_MULTIPLIER = 4.0


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """Immutable per-game tile-grid specification.

    `render_extent_multiplier` controls how much terrain the pipeline fetches and renders
    relative to the playable area. CS1 uses `1.0` (no wide-context output). CS2 uses `4.0` so
    the resulting raster covers the worldmap extent (4× linear, 16× area) — the export adapter
    then crops the centre 1/multiplier² for `heightmap.png` and uses the full thing as
    `worldmap.png`.
    """

    target_id: str
    tile_side_metres: float
    grid_dimension: int
    default_radius_tiles: int
    render_extent_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.tile_side_metres <= 0.0:
            raise ValueError(
                f"tile_side_metres must be strictly positive, got {self.tile_side_metres}"
            )
        if self.grid_dimension <= 0:
            raise ValueError(f"grid_dimension must be strictly positive, got {self.grid_dimension}")
        if self.grid_dimension % 2 == 0:
            # A center tile only exists on odd-dimension grids. Both CS1 (9) and CS2 (21) are
            # odd by design — reject an even grid up front so a future regression cannot silently
            # produce an ambiguous "center".
            raise ValueError(
                f"grid_dimension must be odd to have a well-defined center tile, "
                f"got {self.grid_dimension}"
            )
        if self.default_radius_tiles < 0:
            raise ValueError(
                f"default_radius_tiles must be non-negative, got {self.default_radius_tiles}"
            )
        max_radius = (self.grid_dimension - 1) // 2
        if self.default_radius_tiles > max_radius:
            raise ValueError(
                f"default_radius_tiles {self.default_radius_tiles} exceeds the maximum radius "
                f"{max_radius} implied by grid_dimension {self.grid_dimension}"
            )
        if self.render_extent_multiplier < 1.0:
            raise ValueError(
                f"render_extent_multiplier must be >= 1.0 (got {self.render_extent_multiplier}); "
                "the render extent always covers at least the playable area."
            )

    @property
    def max_radius_tiles(self) -> int:
        """The largest radius that still fits inside `grid_dimension`."""
        return (self.grid_dimension - 1) // 2


_REGISTRY: dict[str, TargetSpec] = {
    CS1_TARGET_ID: TargetSpec(
        target_id=CS1_TARGET_ID,
        tile_side_metres=CS1_TILE_SIDE_METRES,
        grid_dimension=CS1_GRID_DIMENSION,
        default_radius_tiles=CS1_DEFAULT_RADIUS_TILES,
        render_extent_multiplier=CS1_RENDER_EXTENT_MULTIPLIER,
    ),
    CS2_TARGET_ID: TargetSpec(
        target_id=CS2_TARGET_ID,
        tile_side_metres=CS2_TILE_SIDE_METRES,
        grid_dimension=CS2_GRID_DIMENSION,
        default_radius_tiles=CS2_DEFAULT_RADIUS_TILES,
        render_extent_multiplier=CS2_RENDER_EXTENT_MULTIPLIER,
    ),
}


class UnknownTargetError(KeyError):
    """Raised when a `target_id` is not registered in `TARGET_SPECS`."""


def get_target_spec(target_id: str) -> TargetSpec:
    """Return the registered `TargetSpec` for `target_id`, or raise `UnknownTargetError`.

    We deliberately raise our own typed error rather than letting `KeyError` propagate: callers
    at the interfaces layer can translate it into a 400/usage error without sniffing built-ins.
    """
    try:
        return _REGISTRY[target_id]
    except KeyError as error:
        known = sorted(_REGISTRY)
        raise UnknownTargetError(f"Unknown target {target_id!r}. Known targets: {known}") from error


def registered_target_ids() -> tuple[str, ...]:
    """Sorted tuple of registered target ids. Sorted so iteration is deterministic."""
    return tuple(sorted(_REGISTRY))
