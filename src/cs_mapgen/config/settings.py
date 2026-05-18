"""Pydantic settings loaded from `CS_MAPGEN_*` environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CACHE_DIRECTORY = Path("./data/cache").resolve()
DEFAULT_OUTPUT_DIRECTORY = Path("./data/output").resolve()
DEFAULT_DEM_PROVIDER = "srtm"
DEFAULT_SEED = 0


class Settings(BaseSettings):
    """Project-wide configuration. All values are validated at startup."""

    model_config = SettingsConfigDict(
        env_prefix="CS_MAPGEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    cache_directory: Path = Field(default=DEFAULT_CACHE_DIRECTORY)
    output_directory: Path = Field(default=DEFAULT_OUTPUT_DIRECTORY)
    dem_provider: str = Field(default=DEFAULT_DEM_PROVIDER)
    default_seed: int = Field(default=DEFAULT_SEED)
    srtm_base_url: str = Field(
        default="https://step.esa.int/auxdata/dem/SRTMGL1/",
        description="HTTPS root for SRTM 1-arcsecond tiles. Public mirror, no auth required.",
    )


def load_settings() -> Settings:
    return Settings()
