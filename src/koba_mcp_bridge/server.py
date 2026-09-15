from __future__ import annotations

import os
import platform
from datetime import UTC, datetime

from fastmcp import FastMCP
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware
from mcp.types import ToolAnnotations

from . import __version__

_STARTED_AT = datetime.now(UTC).isoformat()
_READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=False,
)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required when OAuth is enabled")
    return value


def _allowed_github_users() -> set[str]:
    raw = _required_env("KOBA_OAUTH_ALLOWED_GITHUB_USERS")
    return {item.strip().casefold() for item in raw.split(",") if item.strip()}


def _github_user_allowed(ctx: AuthContext) -> bool:
    if ctx.token is None:
        return False
    login = str(ctx.token.claims.get("login", "")).casefold()
    return bool(login) and login in _allowed_github_users()


def _build_auth() -> tuple[GitHubProvider | None, list[AuthMiddleware]]:
    if not _env_bool("KOBA_OAUTH_ENABLED"):
        return None, []

    provider = GitHubProvider(
        client_id=_required_env("KOBA_OAUTH_GITHUB_CLIENT_ID"),
        client_secret=_required_env("KOBA_OAUTH_GITHUB_CLIENT_SECRET"),
        base_url=os.getenv("KOBA_OAUTH_BASE_URL", "https://mcp-bridge.koba-nexus.ru"),
        required_scopes=["read:user"],
        jwt_signing_key=_required_env("KOBA_OAUTH_JWT_SIGNING_KEY"),
        require_authorization_consent=True,
        fallback_refresh_token_expiry_seconds=30 * 24 * 60 * 60,
        fastmcp_access_token_expiry_seconds=30 * 60,
    )
    return provider, [AuthMiddleware(auth=_github_user_allowed)]


_auth, _auth_middleware = _build_auth()

mcp = FastMCP(
    "koba-mcp-bridge",
    version=__version__,
    instructions=(
        "Koba MCP Bridge exposes controlled local tools and long-running "
        "worker tasks to MCP clients."
    ),
    auth=_auth,
    middleware=_auth_middleware,
)


@mcp.tool(
    title="Bridge ping",
    annotations=_READ_ONLY_LOCAL,
)
def bridge_ping() -> dict[str, str]:
    """Check that the bridge is alive and reachable."""
    return {
        "status": "ok",
        "service": "koba-mcp-bridge",
        "version": __version__,
        "time": datetime.now(UTC).isoformat(),
    }


@mcp.tool(
    title="Bridge build info",
    annotations=_READ_ONLY_LOCAL,
)
def bridge_build_info() -> dict[str, str]:
    """Return build metadata for the currently running bridge instance."""
    return {
        "service": "koba-mcp-bridge",
        "version": __version__,
        "commit": os.getenv("KOBA_BUILD_SHA", "unknown"),
        "built_at": os.getenv("KOBA_BUILD_TIME", "unknown"),
        "started_at": _STARTED_AT,
        "python": platform.python_version(),
    }


@mcp.tool(
    title="Bridge capabilities",
    annotations=_READ_ONLY_LOCAL,
)
def bridge_capabilities() -> dict[str, object]:
    """Return the currently enabled high-level bridge capabilities."""
    features = ["mcp", "streamable-http", "opentelemetry"]
    if _auth is not None:
        features.append("github-oauth")
    return {
        "workers": [],
        "features": features,
        "status": "bootstrap",
    }


def _split_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


app = mcp.http_app(
    path="/mcp",
    allowed_hosts=_split_env(
        "MCP_ALLOWED_HOSTS",
        "localhost:*,127.0.0.1:*,[::1]:*",
    ),
    allowed_origins=_split_env(
        "MCP_ALLOWED_ORIGINS",
        "http://localhost:*,http://127.0.0.1:*,http://[::1]:*",
    ),
)
