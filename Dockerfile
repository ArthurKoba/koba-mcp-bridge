FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ARG BUILD_SHA=unknown
ARG BUILD_TIME=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTMCP_HOME=/data/fastmcp \
    BUILD_SHA=${BUILD_SHA} \
    BUILD_TIME=${BUILD_TIME}

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN uv sync --no-dev \
    && mkdir -p /data/fastmcp

EXPOSE 8000

CMD ["uv", "run", "opentelemetry-instrument", "uvicorn", "koba_mcp_bridge.server:app", "--host", "0.0.0.0", "--port", "8000"]
