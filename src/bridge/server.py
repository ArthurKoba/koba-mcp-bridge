from __future__ import annotations

import os
import platform
from datetime import UTC, datetime

from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware
from starlette.applications import Starlette

from common.config import env_bool, env_list
from common.runtime_annotations import READ_EXTERNAL, READ_ONLY_LOCAL
from common.secrets import SecretError, resolve_config_secret
from common.secrets_tools import register_secrets_tools

from . import __version__

_STARTED_AT = datetime.now(UTC).isoformat()
_CHATGPT_OAUTH_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"


def _github_oauth_value(secret_name: str) -> str:
    try:
        return resolve_config_secret("github/oauth", secret_name).strip()
    except SecretError as exc:
        raise RuntimeError(
            f"unable to load GitHub OAuth {secret_name!r} from Infisical: {exc}"
        ) from exc


def _allowed_github_users() -> set[str]:
    raw = _github_oauth_value("ALLOWED_USERS")
    return {item.strip().casefold() for item in raw.split(",") if item.strip()}


def _github_user_allowed(ctx: AuthContext) -> bool:
    if ctx.token is None:
        return False
    login = str(ctx.token.claims.get("login", "")).casefold()
    return bool(login) and login in _allowed_github_users()


def _build_auth() -> tuple[GitHubProvider | None, list[AuthMiddleware]]:
    if not env_bool("OAUTH_ENABLED"):
        return None, []

    provider = GitHubProvider(
        client_id=_github_oauth_value("CLIENT_ID"),
        client_secret=_github_oauth_value("CLIENT_SECRET"),
        base_url=os.getenv("OAUTH_BASE_URL", "https://mcp.koba-nexus.ru"),
        required_scopes=["read:user"],
        jwt_signing_key=_github_oauth_value("JWT_SIGNING_KEY"),
        allowed_client_redirect_uris=[_CHATGPT_OAUTH_REDIRECT],
        require_authorization_consent="external",
        enable_cimd=False,
        fallback_refresh_token_expiry_seconds=30 * 24 * 60 * 60,
        fastmcp_access_token_expiry_seconds=30 * 60,
    )
    return provider, [AuthMiddleware(auth=_github_user_allowed)]


def _backend_url(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _configured_backends() -> dict[str, str]:
    return {
        "github": _backend_url("GITHUB_URL", "http://github:8000/mcp"),
        "gitlab": _backend_url("GITLAB_URL", "http://gitlab:8000/mcp"),
        "files": _backend_url("FILES_URL", "http://files:8000/mcp"),
        "http": _backend_url("CURL_URL", "http://curl:8000/mcp"),
        "analysis": _backend_url(
            "ANALYSIS_URL",
            "http://analysis:8000/mcp",
        ),
    }


def _proxy(name: str, url: str) -> FastMCP:
    return create_proxy(url, name=f"{name}-backend", mode="auto")


def _public_facade(name: str, backend_name: str, backend_url: str) -> FastMCP:
    surface = FastMCP(
        name,
        version=__version__,
        auth=_auth,
        middleware=_auth_middleware,
    )
    surface.mount(server=_proxy(backend_name, backend_url))
    return surface


def _mount_aggregate_backends(
    server: FastMCP,
    backends: dict[str, str],
) -> None:
    for name in ("github", "files", "http", "analysis"):
        server.mount(server=_proxy(name, backends[name]))
    server.mount(
        server=_proxy("gitlab", backends["gitlab"]),
        namespace="gitlab",
    )


_auth, _auth_middleware = _build_auth()
_BACKENDS = _configured_backends()

mcp = FastMCP(
    "mcp-bridge",
    version=__version__,
    instructions=(
        "Authenticated edge gateway for isolated modules. "
        "GitHub, GitLab, Files, curl and analysis execute in private services. "
        "Secrets are never returned as plaintext."
    ),
    auth=_auth,
    middleware=_auth_middleware,
)

github_surface = _public_facade(
    "github",
    "github",
    _BACKENDS["github"],
)
gitlab_surface = _public_facade(
    "gitlab",
    "gitlab",
    _BACKENDS["gitlab"],
)
files_surface = _public_facade(
    "files",
    "files",
    _BACKENDS["files"],
)
http_surface = _public_facade(
    "curl",
    "http",
    _BACKENDS["http"],
)
analysis_surface = _public_facade(
    "analysis",
    "analysis",
    _BACKENDS["analysis"],
)

_mount_aggregate_backends(mcp, _BACKENDS)


@mcp.tool(title="Bridge ping", annotations=READ_ONLY_LOCAL)
def bridge_ping() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "mcp-bridge",
        "version": __version__,
        "time": datetime.now(UTC).isoformat(),
    }


@mcp.tool(title="Bridge build info", annotations=READ_ONLY_LOCAL)
def bridge_build_info() -> dict[str, str]:
    return {
        "service": "mcp-bridge",
        "version": __version__,
        "commit": os.getenv("BUILD_SHA", "unknown"),
        "built_at": os.getenv("BUILD_TIME", "unknown"),
        "started_at": _STARTED_AT,
        "python": platform.python_version(),
    }


@mcp.tool(title="Bridge capabilities", annotations=READ_ONLY_LOCAL)
def bridge_capabilities() -> dict[str, object]:
    return {
        "backends": sorted(_BACKENDS),
        "public_surfaces": [
            "/mcp",
            "/github/mcp",
            "/gitlab/mcp",
            "/files/mcp",
            "/http/mcp",
            "/analysis/mcp",
        ],
        "features": [
            "mcp",
            "streamable-http",
            "gateway",
            "infisical-secrets",
            "github",
            "gitlab",
            "files",
            "curl",
            "analysis",
        ],
        "status": "active",
    }


register_secrets_tools(mcp, READ_EXTERNAL)


_allowed_hosts = env_list(
    "MCP_ALLOWED_HOSTS",
    "localhost:*,127.0.0.1:*,[::1]:*",
)
_allowed_origins = env_list(
    "MCP_ALLOWED_ORIGINS",
    "http://localhost:*,http://127.0.0.1:*,http://[::1]:*",
)


def _http_app(surface: FastMCP) -> Starlette:
    return surface.http_app(
        path="/mcp",
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    )


app = _http_app(mcp)
app.mount("/github", _http_app(github_surface))
app.mount("/gitlab", _http_app(gitlab_surface))
app.mount("/files", _http_app(files_surface))
app.mount("/http", _http_app(http_surface))
app.mount("/analysis", _http_app(analysis_surface))
