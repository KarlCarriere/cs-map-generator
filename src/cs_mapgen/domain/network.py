"""Road network value objects — framework-free graph representation."""

from __future__ import annotations

from dataclasses import dataclass

from cs_mapgen.domain.geometry import Projection

MIN_EDGE_VERTICES = 2


@dataclass(frozen=True, slots=True)
class RoadNode:
    """A graph vertex in the working CRS."""

    node_id: int
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class RoadEdge:
    """A directed-or-undirected edge between two RoadNodes.

    Geometry is a tuple of `(x, y)` vertices including endpoints, in `crs` of the parent network.
    `highway_class` is the OSM `highway=` tag value (e.g. `motorway`, `residential`).
    """

    source: int
    target: int
    geometry: tuple[tuple[float, float], ...]
    highway_class: str
    length_metres: float

    def __post_init__(self) -> None:
        if len(self.geometry) < MIN_EDGE_VERTICES:
            raise ValueError(
                f"RoadEdge geometry must have at least {MIN_EDGE_VERTICES} vertices"
            )
        if self.length_metres < 0:
            raise ValueError(f"Edge length must be non-negative, got {self.length_metres}")
        if not self.highway_class:
            raise ValueError("highway_class must be a non-empty string")


@dataclass(frozen=True, slots=True)
class RoadNetwork:
    """An immutable road graph in a single CRS."""

    nodes: tuple[RoadNode, ...]
    edges: tuple[RoadEdge, ...]
    crs: Projection

    def __post_init__(self) -> None:
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("RoadNetwork nodes must have unique node_id values")
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError(
                    f"Edge {edge.source}->{edge.target} references unknown node id"
                )

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)
