"""OSMnx-backed road source.

OSMnx 2.x signature: `osmnx.graph.graph_from_bbox(bbox=(west, south, east, north), ...)`.
The bbox tuple ordering changed in OSMnx 2.0 (was four positional args in 1.x). We pin to
~=2.1 in pyproject.toml so this signature is stable.

Determinism: OSMnx queries Overpass, which can return varying data over time. For deterministic
test runs we accept an optional `graph_loader` callable that bypasses the live query and reads a
pickled / GraphML fixture instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.network import RoadEdge, RoadNetwork, RoadNode

if TYPE_CHECKING:
    import networkx as nx

DEFAULT_NETWORK_TYPE = "drive"


class OSMnxRoadSource:
    """Wraps `osmnx.graph.graph_from_bbox` and converts the result into a `RoadNetwork`."""

    def __init__(
        self,
        graph_loader: Callable[[GeoBounds, str], object] | None = None,
    ) -> None:
        self._graph_loader = graph_loader

    def fetch_roads(
        self,
        bounds: GeoBounds,
        network_type: str,
        context: StageContext,
    ) -> RoadNetwork:
        graph = self._load_graph(bounds, network_type, context)
        return _graph_to_road_network(graph)

    def _load_graph(
        self,
        bounds: GeoBounds,
        network_type: str,
        context: StageContext,
    ) -> object:
        if self._graph_loader is not None:
            return self._graph_loader(bounds, network_type)
        # Local import — OSMnx pulls in a heavy stack and we want test runs that inject a
        # graph_loader to avoid loading it at all.
        import osmnx  # noqa: PLC0415  (local import is intentional)

        context.logger.info(
            "osmnx.fetch",
            extra={
                "bbox": bounds.as_tuple(),
                "network_type": network_type,
            },
        )
        return osmnx.graph.graph_from_bbox(
            bbox=bounds.as_tuple(),
            network_type=network_type,
            simplify=True,
            retain_all=False,
            truncate_by_edge=False,
        )


def _graph_to_road_network(graph: object) -> RoadNetwork:
    # We type the graph as `object` at the boundary because importing networkx eagerly would
    # leak a dependency into a layer that does not require it for fixture-driven tests.
    nx_graph = _as_networkx(graph)

    nodes = tuple(
        sorted(
            (
                RoadNode(node_id=int(node_id), x=float(data["x"]), y=float(data["y"]))
                for node_id, data in nx_graph.nodes(data=True)
            ),
            key=lambda node: node.node_id,
        )
    )

    node_coords = {node.node_id: (node.x, node.y) for node in nodes}

    edges = tuple(
        sorted(
            (
                _edge_from_nx(source, target, data, node_coords)
                for source, target, data in nx_graph.edges(data=True)
            ),
            key=lambda edge: (edge.source, edge.target, edge.highway_class),
        )
    )

    return RoadNetwork(nodes=nodes, edges=edges, crs=Projection.wgs84())


def _as_networkx(graph: object) -> nx.Graph:
    import networkx as nx  # noqa: PLC0415

    if not isinstance(graph, nx.Graph):
        raise TypeError(f"Expected a networkx graph, got {type(graph).__name__}")
    return graph


def _edge_from_nx(
    source: object,
    target: object,
    data: dict[str, object],
    node_coords: dict[int, tuple[float, float]],
) -> RoadEdge:
    highway = data.get("highway", "unclassified")
    if isinstance(highway, list):
        highway_class = str(highway[0])
    else:
        highway_class = str(highway)

    length = float(data.get("length", 0.0))
    source_id = int(source)  # type: ignore[arg-type]
    target_id = int(target)  # type: ignore[arg-type]
    geometry = _extract_geometry(data, source_id, target_id, node_coords)

    return RoadEdge(
        source=source_id,
        target=target_id,
        geometry=geometry,
        highway_class=highway_class,
        length_metres=length,
    )


def _extract_geometry(
    data: dict[str, object],
    source_id: int,
    target_id: int,
    node_coords: dict[int, tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    # OSMnx attaches a shapely LineString in `geometry` only for simplified multi-vertex edges;
    # straight two-node edges have no `geometry` field, and the implicit geometry is the
    # source→target segment derived from the node coordinates.
    geom = data.get("geometry")
    if geom is not None:
        coords = getattr(geom, "coords", None)
        if coords is not None:
            return tuple((float(x), float(y)) for x, y in coords)
    return (node_coords[source_id], node_coords[target_id])
