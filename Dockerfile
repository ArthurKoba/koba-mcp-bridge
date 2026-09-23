FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ARG BUILD_SHA=unknown
ARG BUILD_TIME=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTMCP_HOME=/data/fastmcp \
    FILE_ROOT=/files \
    HOME=/home/bridge \
    BUILD_SHA=${BUILD_SHA} \
    BUILD_TIME=${BUILD_TIME}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN uv sync --no-dev \
    && mkdir -p /data/fastmcp /files/objects/sha256 /files/tmp /home/bridge \
    && chown -R 1000:1000 /data /files /home/bridge

COPY deploy/docker-entrypoint.sh /usr/local/bin/mcp-bridge-entrypoint
RUN chmod 0755 /usr/local/bin/mcp-bridge-entrypoint \
    && test "$(/usr/local/bin/mcp-bridge-entrypoint id -u)" = "1000" \
    && /usr/local/bin/mcp-bridge-entrypoint /app/.venv/bin/python -c "import koba_mcp_bridge.server"

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/mcp-bridge-entrypoint"]
CMD ["/app/.venv/bin/opentelemetry-instrument", "/app/.venv/bin/uvicorn", "koba_mcp_bridge.server:app", "--host", "0.0.0.0", "--port", "8000"]
