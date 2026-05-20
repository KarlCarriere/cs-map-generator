"""PNG encoding helpers for grayscale rasters."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

PNG_MODE_GRAYSCALE_16 = "I;16"
PNG_MODE_GRAYSCALE_8 = "L"


def encode_uint16_grayscale_png(pixels: np.ndarray) -> bytes:
    """Encode a 2D uint16 array as a single-channel 16-bit grayscale PNG."""
    if pixels.dtype != np.uint16:
        raise ValueError(f"Expected uint16 pixels, got {pixels.dtype}")
    if pixels.ndim != 2:
        raise ValueError(f"Expected 2D pixels, got shape {pixels.shape}")
    image = Image.fromarray(pixels, mode=PNG_MODE_GRAYSCALE_16)
    buffer = io.BytesIO()
    # `optimize=False` keeps the encoder deterministic across PIL minor versions; `optimize=True`
    # can change byte output based on heuristic improvements.
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def encode_uint8_grayscale_png(pixels: np.ndarray) -> bytes:
    """Encode a 2D uint8 array as a single-channel 8-bit grayscale PNG."""
    if pixels.dtype != np.uint8:
        raise ValueError(f"Expected uint8 pixels, got {pixels.dtype}")
    if pixels.ndim != 2:
        raise ValueError(f"Expected 2D pixels, got shape {pixels.shape}")
    image = Image.fromarray(pixels, mode=PNG_MODE_GRAYSCALE_8)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def resample_uint16_nearest(pixels: np.ndarray, target_side: int) -> np.ndarray:
    """Nearest-neighbour resample of a square uint16 image to (target_side, target_side)."""
    if pixels.ndim != 2:
        raise ValueError(f"Expected 2D pixels, got shape {pixels.shape}")
    rows, cols = pixels.shape
    row_indices = np.linspace(0, rows - 1, target_side).round().astype(np.int64)
    col_indices = np.linspace(0, cols - 1, target_side).round().astype(np.int64)
    return pixels[np.ix_(row_indices, col_indices)].astype(np.uint16, copy=False)


def resample_uint16_bilinear(pixels: np.ndarray, target_side: int) -> np.ndarray:
    """Bilinear resample of a square uint16 image to (target_side, target_side).

    Use this for continuous-field rasters (heightmaps, worldmaps). For categorical / boolean
    rasters use `resample_bool_nearest` — bilinear interpolation would fabricate intermediate
    values that don't correspond to any source class.
    """
    if pixels.dtype != np.uint16:
        raise ValueError(f"Expected uint16 pixels, got {pixels.dtype}")
    if pixels.ndim != 2:
        raise ValueError(f"Expected 2D pixels, got shape {pixels.shape}")
    interpolated = bilinear_resample_2d(pixels.astype(np.float32, copy=False), target_side)
    return np.clip(np.round(interpolated), 0.0, 65535.0).astype(np.uint16)


def fill_nodata_nearest_valid(
    values: np.ndarray,
    valid_mask: np.ndarray,
) -> np.ndarray:
    """Replace each invalid pixel with the value of its nearest valid neighbour.

    SRTM voids and tile gaps leave large negative sentinels (`-32768` or `-9999`) in the
    elevation array. Bilinear resampling without this fill smears those sentinels into adjacent
    real pixels, producing artificial black holes and uneven patches after absolute uint16
    encoding. Filling before resample keeps the validity mask intact (downstream stages still
    know which pixels were originally nodata) while ensuring the interpolation operates on
    sensible neighbour values.

    Returns the input unchanged when `valid_mask` is all-True (no fill needed) or all-False
    (nothing to fill from — caller should fail before this point).
    """
    if values.shape != valid_mask.shape:
        raise ValueError(
            f"values {values.shape} and valid_mask {valid_mask.shape} must have the same shape"
        )
    if bool(valid_mask.all()):
        return values
    if not bool(valid_mask.any()):
        return values
    from scipy.ndimage import distance_transform_edt  # noqa: PLC0415

    # `distance_transform_edt(input)` with `return_indices=True` returns the indices of the
    # nearest ZERO-valued pixel for each input pixel. We feed `~valid_mask` so invalid pixels
    # (True) get the indices of their nearest valid (False) neighbour; valid pixels point to
    # themselves at distance 0.
    indices = distance_transform_edt(~valid_mask, return_indices=True)[1]
    return values[indices[0], indices[1]]


def bilinear_resample_2d(values: np.ndarray, target_side: int) -> np.ndarray:
    """Bilinear resample of an arbitrary float 2D array to (target_side, target_side).

    Returns a fresh `float32` array. Determinism: pure NumPy, no SciPy/scikit-image — the
    output is bit-identical across runs given the same input.

    No-op when the input is already at the target side (returns the input cast to float32).
    """
    if values.ndim != 2:
        raise ValueError(f"Expected 2D values, got shape {values.shape}")
    rows, cols = values.shape
    if rows == target_side and cols == target_side:
        return values.astype(np.float32, copy=False)

    source = values.astype(np.float32, copy=False)
    row_coords = np.linspace(0.0, rows - 1, target_side, dtype=np.float64)
    col_coords = np.linspace(0.0, cols - 1, target_side, dtype=np.float64)

    row_floors = np.floor(row_coords).astype(np.int64)
    col_floors = np.floor(col_coords).astype(np.int64)
    row_ceils = np.minimum(row_floors + 1, rows - 1)
    col_ceils = np.minimum(col_floors + 1, cols - 1)

    row_fraction = (row_coords - row_floors).astype(np.float32)[:, None]
    col_fraction = (col_coords - col_floors).astype(np.float32)[None, :]

    top_left = source[np.ix_(row_floors, col_floors)]
    top_right = source[np.ix_(row_floors, col_ceils)]
    bottom_left = source[np.ix_(row_ceils, col_floors)]
    bottom_right = source[np.ix_(row_ceils, col_ceils)]

    top_row = top_left * (1.0 - col_fraction) + top_right * col_fraction
    bottom_row = bottom_left * (1.0 - col_fraction) + bottom_right * col_fraction
    return (top_row * (1.0 - row_fraction) + bottom_row * row_fraction).astype(np.float32)


def resample_bool_nearest(mask: np.ndarray, target_side: int) -> np.ndarray:
    """Nearest-neighbour resample of a boolean mask to (target_side, target_side).

    Nearest-neighbour is required for categorical/boolean rasters — bilinear or cubic would
    produce fractional values which `Pillow` cannot represent in a binary PNG. Boundary cells
    where the mask is ambiguous get the closest source pixel's value, which is the standard
    treatment for resampling categorical data.
    """
    if mask.ndim != 2:
        raise ValueError(f"Expected 2D mask, got shape {mask.shape}")
    rows, cols = mask.shape
    row_indices = np.linspace(0, rows - 1, target_side).round().astype(np.int64)
    col_indices = np.linspace(0, cols - 1, target_side).round().astype(np.int64)
    return mask[np.ix_(row_indices, col_indices)].astype(np.bool_, copy=False)
