"""Prepare roads: reproject the road graph into the working CRS and filter by class."""

from __future__ import annotations

from dataclasses import dataclass

from cs_mapgen.application.ports import Reprojector
from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.prepare_terrain import PrepareTerrainResult
from cs_mapgen.domain.network import RoadEdge, RoadNetwork
from cs_mapgen.domain.raster import Heightmap

DEFAULT_HIGHWAY_ALLOWLIST: tuple[str, ...] = (
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "unclassified",
)


@dataclass(frozen=True, slots=True)
class PrepareRoadsResult:
    heightmap: Heightmap
    road_network: RoadNetwork


class PrepareRoadsStage:
    """Reproject + filter the road network.

    Inputs CRS: the OSMSource's native output CRS (EPSG:4326 for OSMnx).
    Output CRS: `context.working_crs`.

    Simplification + intersection consolidation tolerances are in metres and therefore require
    the metric working CRS, which is why the reprojection happens before any topology op.
    """

    name = "prepare_roads"

    def __init__(
        self,
        reprojector: Reprojector,
        highway_allowlist: tuple[str, ...] = DEFAULT_HIGHWAY_ALLOWLIST,
    ) -> None:
        self._reprojector = reprojector
        self._highway_allowlist = highway_allowlist

    def run(self, inputs: PrepareTerrainResult, context: StageContext) -> PrepareRoadsResult:
        reprojected = self._reprojector.reproject_network(
            inputs.road_network, context.working_crs
        )
        filtered_edges = self._filter_by_class(reprojected.edges, self._highway_allowlist)
        # Drop nodes that no surviving edge references.
        active_node_ids = {edge.source for edge in filtered_edges} | {
            edge.target for edge in filtered_edges
        }
        # Sort nodes by id so the final tuple ordering is deterministic regardless of dict
        # iteration order upstream.
        surviving_nodes = tuple(
            sorted(
                (node for node in reprojected.nodes if node.node_id in active_node_ids),
                key=lambda node: node.node_id,
            )
        )
        sorted_edges = tuple(
            sorted(filtered_edges, key=lambda edge: (edge.source, edge.target))
        )
        filtered_network = RoadNetwork(
            nodes=surviving_nodes,
            edges=sorted_edges,
            crs=context.working_crs,
        )
        return PrepareRoadsResult(heightmap=inputs.heightmap, road_network=filtered_network)

    @staticmethod
    def _filter_by_class(
        edges: tuple[RoadEdge, ...],
        allowlist: tuple[str, ...],
    ) -> tuple[RoadEdge, ...]:
        allowed = frozenset(allowlist)
        return tuple(edge for edge in edges if edge.highway_class in allowed)
