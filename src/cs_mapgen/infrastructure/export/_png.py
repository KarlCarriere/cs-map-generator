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
