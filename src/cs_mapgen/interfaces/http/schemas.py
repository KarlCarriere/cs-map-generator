"""Pydantic schemas for the HTTP surface. Boundary types only — never used inside the domain.

The map extent is expressed as a Pydantic discriminated union (`{"kind": "center", ...}` vs.
`{"kind": "bbox", ...}`). Why discriminated union rather than a single endpoint with a manual
validator: Pydantic's `discriminator=` produces a precise `union_tag_invalid` error path,
which FastAPI surfaces as a 422 with a per-field message — that beats a hand-rolled validator
on OpenAPI clarity and error quality with no extra code.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_SEED = 0


class HealthResponse(BaseModel):
    status: str = Field(description="Liveness status. Always 'ok' when the API is up.")
    version: str = Field(description="Current cs-mapgen version.")


class CenterInput(BaseModel):
    """Centre-coordinate map intent."""

    # `extra="forbid"` so a payload that mixes center- and bbox-shaped keys (e.g. supplies
    # both `lat`/`lon` and `west`/`south`/`east`/`north` under a single `kind`) is rejected
    # with a 422 rather than silently dropping the unexpected keys.
    model_config = ConfigDict(extra="forbid")

    kind: Literal["center"] = Field(
        description="Discriminator. Must be the literal 'center' for this shape.",
    )
    lat: float = Field(description="Centre latitude in WGS84 decimal degrees.")
    lon: float = Field(description="Centre longitude in WGS84 decimal degrees.")
    radius_tiles: int | None = Field(
        default=None,
        description=(
            "Number of game tiles in each cardinal direction around the centre. "
            "Defaults to the game-standard radius for the chosen target "
            "(CS1: 4, CS2: 10) when omitted."
        ),
    )


class BboxInput(BaseModel):
    """Explicit-bounds map intent."""

    # See CenterInput.model_config for the rationale.
    model_config = ConfigDict(extra="forbid")

    kind: Literal["bbox"] = Field(
        description="Discriminator. Must be the literal 'bbox' for this shape.",
    )
    west: float = Field(description="Western longitude in WGS84 degrees.")
    south: float = Field(description="Southern latitude in WGS84 degrees.")
    east: float = Field(description="Eastern longitude in WGS84 degrees.")
    north: float = Field(description="Northern latitude in WGS84 degrees.")


MapInput = Annotated[CenterInput | BboxInput, Field(discriminator="kind")]


class GenerateMapRequest(BaseModel):
    input: MapInput = Field(description="Map extent intent (discriminated by `kind`).")
    target: str = Field(description="Export target id, e.g. 'cs1' or 'cs2'.")
    seed: int = Field(default=DEFAULT_SEED, description="Deterministic RNG seed.")
    dump_intermediates: bool = Field(default=False)


class ArtifactResponse(BaseModel):
    name: str
    path: str
    sha256: str
    mime: str


class GenerateMapResponse(BaseModel):
    target: str
    inputs_hash: str
    seed: int
    created_at_utc: str
    artifacts: list[ArtifactResponse]
