"""Unit tests for the water-domain value objects."""

from __future__ import annotations

import numpy as np
import pytest

from cs_mapgen.domain.geometry import Projection
from cs_mapgen.domain.water import (
    CoastlineSegment,
    WaterFeatures,
    WaterMask,
    WaterPolygon,
    Waterway,
)

VALID_TRANSFORM = (1.0, 0.0, 0.0, 0.0, -1.0, 0.0)
SQUARE_RING = (
    (0.0, 0.0),
    (1.0, 0.0),
    (1.0, 1.0),
    (0.0, 1.0),
    (0.0, 0.0),
)


def test_should_construct_water_mask_when_inputs_are_valid() -> None:
    mask_array = np.zeros((4, 4), dtype=np.bool_)
    mask_array[1, 1] = True

    mask = WaterMask(
        mask=mask_array,
        transform=VALID_TRANSFORM,
        crs=Projection.wgs84(),
    )

    assert mask.shape == (4, 4)
    assert mask.coverage_fraction == pytest.approx(1.0 / 16.0)


def test_should_reject_water_mask_when_mask_is_not_2d() -> None:
    bad_mask = np.zeros((4,), dtype=np.bool_)
    with pytest.raises(ValueError, match="2D"):
        WaterMask(mask=bad_mask, transform=VALID_TRANSFORM, crs=Projection.wgs84())


def test_should_reject_water_mask_when_dtype_is_not_bool() -> None:
    int_mask = np.zeros((4, 4), dtype=np.uint8)
    with pytest.raises(ValueError, match="bool"):
        WaterMask(mask=int_mask, transform=VALID_TRANSFORM, crs=Projection.wgs84())  # type: ignore[arg-type]


def test_should_reject_water_mask_when_transform_is_not_six_tuple() -> None:
    mask_array = np.zeros((4, 4), dtype=np.bool_)
    with pytest.raises(ValueError, match="6-tuple"):
        WaterMask(
            mask=mask_array,
            transform=(1.0, 0.0, 0.0),  # type: ignore[arg-type]
            crs=Projection.wgs84(),
        )


def test_should_report_zero_coverage_when_mask_is_empty_size() -> None:
    mask = WaterMask(
        mask=np.zeros((0, 0), dtype=np.bool_),
        transform=VALID_TRANSFORM,
        crs=Projection.wgs84(),
    )
    assert mask.coverage_fraction == 0.0


def test_should_construct_water_polygon_with_exterior_only() -> None:
    polygon = WaterPolygon(exterior=SQUARE_RING)

    assert polygon.exterior == SQUARE_RING
    assert polygon.holes == ()


def test_should_construct_water_polygon_with_holes() -> None:
    inner = ((0.25, 0.25), (0.5, 0.25), (0.5, 0.5), (0.25, 0.25))
    polygon = WaterPolygon(exterior=SQUARE_RING, holes=(inner,))

    assert polygon.holes == (inner,)


def test_should_reject_water_polygon_when_exterior_is_too_short() -> None:
    with pytest.raises(ValueError, match="exterior"):
        WaterPolygon(exterior=((0.0, 0.0), (1.0, 0.0), (0.0, 0.0)))


def test_should_reject_water_polygon_when_hole_is_too_short() -> None:
    with pytest.raises(ValueError, match="hole"):
        WaterPolygon(
            exterior=SQUARE_RING,
            holes=(((0.25, 0.25), (0.5, 0.25), (0.25, 0.25)),),
        )


def test_should_construct_waterway_with_known_class() -> None:
    waterway = Waterway(
        geometry=((0.0, 0.0), (1.0, 1.0)),
        waterway_class="river",
    )
    assert waterway.waterway_class == "river"


def test_should_reject_waterway_when_geometry_too_short() -> None:
    with pytest.raises(ValueError, match="vertices"):
        Waterway(geometry=((0.0, 0.0),), waterway_class="river")


def test_should_reject_waterway_when_class_is_empty() -> None:
    with pytest.raises(ValueError, match="waterway_class"):
        Waterway(geometry=((0.0, 0.0), (1.0, 1.0)), waterway_class="")


def test_should_construct_coastline_segment_when_geometry_is_valid() -> None:
    segment = CoastlineSegment(geometry=((0.0, 0.0), (1.0, 1.0), (2.0, 0.0)))
    assert len(segment.geometry) == 3


def test_should_reject_coastline_segment_when_geometry_too_short() -> None:
    with pytest.raises(ValueError, match="vertices"):
        CoastlineSegment(geometry=((0.0, 0.0),))


def test_should_report_is_empty_when_features_have_no_geometry() -> None:
    features = WaterFeatures(
        polygons=(),
        waterways=(),
        coastlines=(),
        crs=Projection.wgs84(),
    )
    assert features.is_empty is True


def test_should_report_not_empty_when_features_contain_a_polygon() -> None:
    features = WaterFeatures(
        polygons=(WaterPolygon(exterior=SQUARE_RING),),
        waterways=(),
        coastlines=(),
        crs=Projection.wgs84(),
    )
    assert features.is_empty is False


def test_should_be_immutable_after_construction() -> None:
    mask_array = np.zeros((4, 4), dtype=np.bool_)
    mask = WaterMask(
        mask=mask_array,
        transform=VALID_TRANSFORM,
        crs=Projection.wgs84(),
    )
    # frozen=True dataclass — attribute writes must raise.
    with pytest.raises((AttributeError, TypeError)):
        mask.transform = VALID_TRANSFORM  # type: ignore[misc]
