FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
RUN uv sync --no-dev --no-install-project


FROM dependencies AS runtime-base

ARG BUILD_SHA=unknown
ARG BUILD_TIME=unknown

ENV FASTMCP_HOME=/data/fastmcp \
    FILE_ROOT=/files \
    HOME=/home/bridge \
    BUILD_SHA=${BUILD_SHA} \
    BUILD_TIME=${BUILD_TIME}

COPY docker-entrypoint.sh /usr/local/bin/bridge-entrypoint
RUN chmod 0755 /usr/local/bin/bridge-entrypoint \
    && mkdir -p /data/fastmcp /files/objects/sha256 /files/tmp /management /home/bridge \
    && chown -R 1000:1000 /data /files /management /home/bridge

COPY src/common ./src/common

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD /app/.venv/bin/python -c "import socket; s=socket.create_connection(('127.0.0.1', 8000), 2); s.close()" || exit 1

ENTRYPOINT ["/usr/local/bin/bridge-entrypoint"]
CMD ["/app/.venv/bin/python", "-m", "common.asgi"]


FROM runtime-base AS gateway
COPY src/bridge ./src/bridge
ENV ASGI_APP=bridge.server:app


FROM runtime-base AS management
COPY src/management ./src/management
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/files ./src/modules/files
ENV ASGI_APP=management.runtime:app


FROM runtime-base AS github
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/github ./src/modules/github
ENV ASGI_APP=modules.github.runtime:app


FROM runtime-base AS gitlab
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/gitlab ./src/modules/gitlab
ENV ASGI_APP=modules.gitlab.runtime:app


FROM runtime-base AS files
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/files ./src/modules/files
ENV ASGI_APP=modules.files.runtime:app


FROM runtime-base AS curl
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/files ./src/modules/files
COPY src/modules/curl ./src/modules/curl
ENV ASGI_APP=modules.curl.runtime:app


FROM runtime-base AS analysis
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/analysis ./src/modules/analysis
ENV ASGI_APP=modules.analysis.runtime:app


FROM runtime-base AS ghidra
COPY src/modules/__init__.py ./src/modules/__init__.py
COPY src/modules/ghidra ./src/modules/ghidra
ENV ASGI_APP=modules.ghidra.runtime:app


FROM gateway AS final
