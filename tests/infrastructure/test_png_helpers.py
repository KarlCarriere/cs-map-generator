"""Unit tests for `fill_nodata_nearest_valid` in the PNG helper module.

These tests cover the nearest-valid-neighbour fill used to neutralise SRTM void sentinels
before bilinear resampling. All tests are pure NumPy — no I/O, no SciPy mocking required.
"""

from __future__ import annotations

import numpy as np
import pytest

from cs_mapgen.infrastructure.export._png import fill_nodata_nearest_valid

NODATA = np.float32(-32768.0)


# ---------------------------------------------------------------------------
# Test 1 — single invalid pixel in a 3x3 array with an unambiguously closest
#           valid neighbour.
#
#  Layout (values):
#   10  20  30
#   40  ND  60       ND = NODATA sentinel
#   70  80  90
#
#  valid_mask:
#   T   T   T
#   T   F   T
#   T   T   T
#
#  All 8 neighbours of the centre are equidistant (distance = 1 pixel).
#  To make the answer unambiguous we instead place the NODATA at (0, 2) — the
#  top-right corner — whose only single-pixel neighbours are (0, 1) and (1, 2).
#  We assign (0, 1) a value of 55 and (1, 2) a value of 99 and all others a
#  different value (0), then verify the filled cell receives one of those two
#  values (both are at distance 1; scipy picks the lower-index one, which is
#  (0, 1) = 55 in row-major order).
# ---------------------------------------------------------------------------


def test_should_replace_void_pixel_with_nearest_neighbour_value_when_single_void_exists() -> None:
    # Arrange
    values = np.array(
        [
            [0.0, 55.0, NODATA],
            [0.0, 0.0, 99.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    valid_mask = np.array(
        [
            [True, True, False],
            [True, True, True],
            [True, True, True],
        ],
        dtype=np.bool_,
    )
    # (0,1) and (1,2) are both distance-1 neighbours of (0,2).
    # scipy.ndimage.distance_transform_edt scans in row-major order and returns
    # the nearest pixel; for equidistant ties the lower (row,col) index wins —
    # that is (0,1) with value 55.
    expected_filled_value = np.float32(55.0)

    # Act
    result = fill_nodata_nearest_valid(values, valid_mask)

    # Assert
    assert result[0, 2] == expected_filled_value


# ---------------------------------------------------------------------------
# Test 2 — all-valid mask → input returned unchanged.
# ---------------------------------------------------------------------------


def test_should_return_input_unchanged_when_valid_mask_is_all_true() -> None:
    # Arrange
    values = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    valid_mask = np.ones((2, 2), dtype=np.bool_)

    # Act
    result = fill_nodata_nearest_valid(values, valid_mask)

    # Assert
    np.testing.assert_array_equal(result, values)


# ---------------------------------------------------------------------------
# Test 3 — all-invalid mask → input returned unchanged (early-out guard).
# ---------------------------------------------------------------------------


def test_should_return_input_unchanged_when_valid_mask_is_all_false() -> None:
    # Arrange
    values = np.full((3, 3), NODATA, dtype=np.float32)
    valid_mask = np.zeros((3, 3), dtype=np.bool_)

    # Act
    result = fill_nodata_nearest_valid(values, valid_mask)

    # Assert
    np.testing.assert_array_equal(result, values)


# ---------------------------------------------------------------------------
# Test 4 — shape mismatch → ValueError raised.
# ---------------------------------------------------------------------------


def test_should_raise_value_error_when_values_and_valid_mask_shapes_differ() -> None:
    # Arrange
    values = np.zeros((4, 4), dtype=np.float32)
    valid_mask = np.ones((3, 4), dtype=np.bool_)

    # Act / Assert
    with pytest.raises(ValueError, match="same shape"):
        fill_nodata_nearest_valid(values, valid_mask)


# ---------------------------------------------------------------------------
# Test 5 — connected nodata patch in a larger array.
#
#  7x7 array: centre 3x3 block (rows 2-4, cols 2-4) is NODATA; all surrounding
#  cells are 100.0. After fill every formerly-invalid cell must equal 100.0
#  because the nearest valid neighbour from any point in the patch is one of the
#  surrounding cells which all hold the same value.
# ---------------------------------------------------------------------------


def test_should_fill_nodata_patch_with_surrounding_value_when_patch_is_fully_enclosed() -> None:
    # Arrange
    side = 7
    values = np.full((side, side), np.float32(100.0), dtype=np.float32)
    valid_mask = np.ones((side, side), dtype=np.bool_)

    values[2:5, 2:5] = NODATA
    valid_mask[2:5, 2:5] = False

    # Act
    result = fill_nodata_nearest_valid(values, valid_mask)

    # Assert — every originally-invalid cell is now 100.0
    filled_patch = result[2:5, 2:5]
    np.testing.assert_array_equal(filled_patch, np.full((3, 3), np.float32(100.0)))
