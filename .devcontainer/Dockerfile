# GDAL base image — Ubuntu 24.04 + GDAL 3.x + Python 3.12 + GDAL Python bindings.
# We do NOT install rasterio/geopandas system-wide; we install them via `uv sync`
# into a project-local venv that links against the system GDAL.
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.10.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        sudo \
        libgeos-dev \
        libproj-dev \
        proj-data \
        proj-bin \
        libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

ARG USERNAME=vscode
ARG USER_UID=1001
ARG USER_GID=1001
RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -m -s /bin/bash ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

# Install uv. Pin to a release tag for reproducibility — bump deliberately.
ARG UV_VERSION=0.5.4
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && chmod +x /usr/local/bin/uv /usr/local/bin/uvx

USER ${USERNAME}
WORKDIR /workspace

ENV PATH="/workspace/.venv/bin:${PATH}"

CMD ["bash"]
