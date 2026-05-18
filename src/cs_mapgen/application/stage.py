"""Stage Protocol and the per-run context object."""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger, getLogger
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from cs_mapgen.domain.geometry import GeoBounds, Projection

DEFAULT_SEED = 0


@dataclass(frozen=True, slots=True)
class StageContext:
    """Immutable per-run context. All side-effect dependencies (cache dir, RNG, logger) are
    passed explicitly — stages never reach for globals.
    """

    bounds: GeoBounds
    working_crs: Projection
    seed: int
    cache_directory: Path
    output_directory: Path
    dump_intermediates: bool = False
    logger: Logger = field(default_factory=lambda: getLogger("cs_mapgen"))

    def rng(self) -> np.random.Generator:
        """Return a fresh NumPy generator seeded from `self.seed`.

        Each call returns an independent generator so that branches of the pipeline can draw
        without leaking state across stages. Determinism requires that the call order itself is
        deterministic; the pipeline orchestrator guarantees a fixed stage sequence.
        """
        return np.random.default_rng(self.seed)


@runtime_checkable
class Stage(Protocol):
    """A pure transformation from one typed input to one typed output.

    Implementations must be deterministic given the same inputs and context, and must not mutate
    their inputs. Any side effect (HTTP, disk I/O) is delegated to an injected port.
    """

    name: str

    def run(self, inputs: object, context: StageContext) -> object: ...
