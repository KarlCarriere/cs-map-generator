"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from cs_mapgen import __version__
from cs_mapgen.interfaces.http.routers import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="cs-mapgen",
        version=__version__,
        summary="Real-world bbox -> Cities: Skylines 1 / 2 map artifacts.",
        description=(
            "Synchronous map generation endpoint. POST /maps to kick off a pipeline run; the "
            "response carries the export manifest with sha256 of every artifact."
        ),
    )
    app.include_router(router)
    return app


app = create_app()
