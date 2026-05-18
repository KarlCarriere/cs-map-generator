"""Pyproj/rasterio-backed reprojector.

Determinism: GDAL/PROJ reprojection is bitwise deterministic for fixed input grids and the same
PROJ data version. The PROJ version is pinned via the dev container; running outside the
container voids that guarantee.

This adapter is intentionally light on logic — the heavy lifting is delegated to
`rasterio.warp.reproject` (rasters) and `pyproj.Transformer` (vector coordinates). We always
construct transformers with `always_xy=True` to avoid the lon/lat axis-order trap.
"""

from __future__ import annotations

from cs_mapgen.application.ports import Reprojector
from cs_mapgen.domain.geometry import Projection
from cs_mapgen.domain.network import RoadEdge, RoadNetwork, RoadNode
from cs_mapgen.domain.raster import DEMTile

RESAMPLING_BY_NAME: dict[str, int] = {}  # populated lazily to avoid eager rasterio import


class PyprojReprojector(Reprojector):
    """The single Reprojector implementation for v0.1."""

    def reproject_raster(self, tile: DEMTile, target: Projection, resampling: str) -> DEMTile:
        if tile.crs.epsg == target.epsg:
            return tile

        # Local import keeps rasterio out of the import graph for users who only need vector
        # reprojection or who mock the reprojector in tests.
        import numpy as np  # noqa: PLC0415
        from rasterio import Affine  # noqa: PLC0415
        from rasterio.crs import CRS  # noqa: PLC0415
        from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: PLC0415

        resampling_mode = _resolve_resampling(resampling, Resampling)

        src_crs = CRS.from_epsg(tile.crs.epsg)
        dst_crs = CRS.from_epsg(target.epsg)
        src_transform = Affine(*tile.transform)
        src_height, src_width = tile.elevation.shape

        # Compute output grid that covers the source extent at "auto" resolution.
        left, bottom, right, top = _bounds_from_affine(src_transform, src_width, src_height)
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs, src_width, src_height, left, bottom, right, top
        )

        destination = np.full((dst_height, dst_width), tile.nodata, dtype=np.float32)
        reproject(
            source=tile.elevation,
            destination=destination,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            src_nodata=tile.nodata,
            dst_nodata=tile.nodata,
            resampling=resampling_mode,
        )

        return DEMTile(
            elevation=destination,
            transform=tuple(dst_transform)[:6],  # type: ignore[arg-type]
            crs=target,
            nodata=tile.nodata,
            provider=tile.provider,
            resolution_metres=tile.resolution_metres,
        )

    def reproject_network(self, network: RoadNetwork, target: Projection) -> RoadNetwork:
        if network.crs.epsg == target.epsg:
            return network

        from pyproj import Transformer  # noqa: PLC0415

        transformer = Transformer.from_crs(
            f"EPSG:{network.crs.epsg}",
            f"EPSG:{target.epsg}",
            always_xy=True,
        )

        reprojected_nodes = tuple(
            RoadNode(
                node_id=node.node_id,
                x=transformer.transform(node.x, node.y)[0],
                y=transformer.transform(node.x, node.y)[1],
            )
            for node in network.nodes
        )
        reprojected_edges = tuple(
            RoadEdge(
                source=edge.source,
                target=edge.target,
                geometry=_reproject_coords(edge.geometry, transformer),
                highway_class=edge.highway_class,
                length_metres=edge.length_metres,
            )
            for edge in network.edges
        )

        return RoadNetwork(
            nodes=reprojected_nodes,
            edges=reprojected_edges,
            crs=target,
        )


def _bounds_from_affine(
    transform: object,
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    # rasterio.Affine exposes coefficients a,b,c,d,e,f where (a,e) are pixel sizes and (c,f)
    # is the upper-left corner. We compute the geographic extent without importing rasterio
    # types here so this helper stays unit-testable.
    a, b, c, d, e, f = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f  # type: ignore[attr-defined]
    del b, d  # rotation terms unused for axis-aligned grids
    left = c
    top = f
    right = c + a * width
    bottom = f + e * height
    return (left, bottom, right, top)


def _resolve_resampling(name: str, enum_cls: object) -> int:
    mapping = {
        "nearest": enum_cls.nearest,  # type: ignore[attr-defined]
        "bilinear": enum_cls.bilinear,  # type: ignore[attr-defined]
        "cubic": enum_cls.cubic,  # type: ignore[attr-defined]
    }
    if name not in mapping:
        raise ValueError(f"Unsupported resampling mode: {name!r}")
    return mapping[name]


def _reproject_coords(
    coords: tuple[tuple[float, float], ...],
    transformer: object,
) -> tuple[tuple[float, float], ...]:
    if not coords:
        return ()
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    new_xs, new_ys = transformer.transform(xs, ys)  # type: ignore[attr-defined]
    return tuple(zip(new_xs, new_ys, strict=True))
