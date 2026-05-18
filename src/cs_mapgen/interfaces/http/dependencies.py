"""FastAPI dependencies. Wraps the composition root for DI overriding in tests."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from cs_mapgen.application.pipeline import Pipeline
from cs_mapgen.config.settings import Settings, load_settings
from cs_mapgen.interfaces.composition import build_production_pipeline

PipelineFactory = Callable[[Settings, str], Pipeline]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def get_pipeline_factory() -> PipelineFactory:
    return build_production_pipeline
