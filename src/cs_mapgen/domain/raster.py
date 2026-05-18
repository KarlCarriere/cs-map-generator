"""Raster value objects: DEM tiles, heightmaps, and feature masks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cs_mapgen.domain.geometry import GeoBounds, Projection

AFFINE_TUPLE_LENGTH = 6
MIN_HEIGHTMAP_SIDE_PIXELS = 32
HEIGHTMAP_UINT16_DTYPE = np.uint16


@dataclass(frozen=True, slots=True)
class DEMTile:
    """A digital elevation model tile aligned to an affine grid in a known CRS."""

    elevation: NDArray[np.float32]
    transform: tuple[float, float, float, float, float, float]
    crs: Projection
    nodata: float
    provider: str
    resolution_metres: float

    def __post_init__(self) -> None:
        if self.elevation.ndim != 2:
            raise ValueError(
                f"DEM elevation must be 2D (rows, cols), got shape {self.elevation.shape}"
            )
        if len(self.transform) != AFFINE_TUPLE_LENGTH:
            raise ValueError(
                f"Affine transform must be a 6-tuple (a, b, c, d, e, f), got {self.transform}"
            )
        if self.resolution_metres <= 0:
            raise ValueError(f"Resolution must be positive, got {self.resolution_metres}")

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Heightmap:
    """A normalized, quantized uint16 heightmap ready for engine export."""

    pixels: NDArray[np.uint16]
    width: int
    height: int
    height_scale_metres: float
    sea_level_metres: float
    bounds: GeoBounds

    def __post_init__(self) -> None:
        if self.pixels.dtype != HEIGHTMAP_UINT16_DTYPE:
            raise ValueError(
                f"Heightmap pixels must be uint16, got {self.pixels.dtype}"
            )
        if self.pixels.shape != (self.height, self.width):
            raise ValueError(
                f"Pixel shape {self.pixels.shape} does not match declared "
                f"(height={self.height}, width={self.width})"
            )
        if self.width < MIN_HEIGHTMAP_SIDE_PIXELS or self.height < MIN_HEIGHTMAP_SIDE_PIXELS:
            raise ValueError(
                f"Heightmap side must be at least {MIN_HEIGHTMAP_SIDE_PIXELS} pixels"
            )
        if self.height_scale_metres <= 0:
            raise ValueError("height_scale_metres must be positive")
        if self.sea_level_metres < 0 or self.sea_level_metres >= self.height_scale_metres:
            raise ValueError(
                "sea_level_metres must lie within [0, height_scale_metres)"
            )


@dataclass(frozen=True, slots=True)
class WaterMask:
    """A binary water mask aligned to the heightmap grid."""

    mask: NDArray[np.bool_]
    transform: tuple[float, float, float, float, float, float]
    crs: Projection

    def __post_init__(self) -> None:
        if self.mask.ndim != 2:
            raise ValueError(f"WaterMask must be 2D, got shape {self.mask.shape}")


@dataclass(frozen=True, slots=True)
class VegetationMask:
    """Vegetation density 0..1 aligned to the heightmap grid."""

    density: NDArray[np.float32]
    transform: tuple[float, float, float, float, float, float]
    crs: Projection

    def __post_init__(self) -> None:
        if self.density.ndim != 2:
            raise ValueError(f"VegetationMask must be 2D, got shape {self.density.shape}")


@dataclass(frozen=True, slots=True)
class LandUseMap:
    """A categorical land-use raster with an integer-to-label legend."""

    categories: NDArray[np.uint8]
    legend: tuple[tuple[int, str], ...]
    transform: tuple[float, float, float, float, float, float]
    crs: Projection

    def __post_init__(self) -> None:
        if self.categories.ndim != 2:
            raise ValueError(f"LandUseMap must be 2D, got shape {self.categories.shape}")
        legend_codes = [code for code, _ in self.legend]
        if len(set(legend_codes)) != len(legend_codes):
            raise ValueError("Legend codes must be unique")
