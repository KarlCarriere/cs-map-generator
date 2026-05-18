"""Unit tests for the per-game tile-grid registry."""

from __future__ import annotations

import pytest

from cs_mapgen.domain.target_specs import (
    CS1_DEFAULT_RADIUS_TILES,
    CS1_GRID_DIMENSION,
    CS1_TILE_SIDE_METRES,
    CS2_DEFAULT_RADIUS_TILES,
    CS2_GRID_DIMENSION,
    CS2_TILE_SIDE_METRES,
    TargetSpec,
    UnknownTargetError,
    get_target_spec,
    registered_target_ids,
)


def test_should_return_cs1_spec_when_target_id_is_cs1() -> None:
    spec = get_target_spec("cs1")

    assert spec.target_id == "cs1"
    assert spec.tile_side_metres == CS1_TILE_SIDE_METRES
    assert spec.grid_dimension == CS1_GRID_DIMENSION
    assert spec.default_radius_tiles == CS1_DEFAULT_RADIUS_TILES
    assert spec.max_radius_tiles == 4


def test_should_return_cs2_spec_when_target_id_is_cs2() -> None:
    spec = get_target_spec("cs2")

    assert spec.target_id == "cs2"
    assert spec.tile_side_metres == CS2_TILE_SIDE_METRES
    assert spec.grid_dimension == CS2_GRID_DIMENSION
    assert spec.default_radius_tiles == CS2_DEFAULT_RADIUS_TILES
    assert spec.max_radius_tiles == 10


def test_should_raise_unknown_target_error_when_target_id_is_unregistered() -> None:
    with pytest.raises(UnknownTargetError):
        get_target_spec("cs7-unobtainium")


def test_should_return_sorted_target_ids_when_listing_registry() -> None:
    ids = registered_target_ids()

    assert ids == tuple(sorted(ids))
    assert "cs1" in ids
    assert "cs2" in ids


def test_should_reject_target_spec_when_grid_dimension_is_even() -> None:
    with pytest.raises(ValueError, match="odd"):
        TargetSpec(
            target_id="even-grid",
            tile_side_metres=1000.0,
            grid_dimension=10,
            default_radius_tiles=4,
        )


def test_should_reject_target_spec_when_default_radius_exceeds_grid() -> None:
    with pytest.raises(ValueError, match="exceeds the maximum radius"):
        TargetSpec(
            target_id="too-large",
            tile_side_metres=1000.0,
            grid_dimension=9,
            default_radius_tiles=5,
        )


def test_should_reject_target_spec_when_tile_side_is_zero_or_negative() -> None:
    with pytest.raises(ValueError, match="tile_side_metres"):
        TargetSpec(
            target_id="zero-side",
            tile_side_metres=0.0,
            grid_dimension=9,
            default_radius_tiles=0,
        )
