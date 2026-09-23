from __future__ import annotations

import os
import platform
from datetime import UTC, datetime

from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware

from . import __version__
from .runtime_annotations import READ_EXTERNAL, READ_ONLY_LOCAL
from .secrets import SecretError, resolve_config_secret
from .secrets_tools import register_secrets_tools

_STARTED_AT = datetime.now(UTC).isoformat()
_CHATGPT_OAUTH_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    if not _env_bool("OAUTH_ENABLED"):
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
        "github": _backend_url("GITHUB_MCP_URL", "http://github-mcp:8000/mcp"),
        "gitlab": _backend_url("GITLAB_MCP_URL", "http://gitlab-mcp:8000/mcp"),
        "files": _backend_url("FILES_MCP_URL", "http://files-mcp:8000/mcp"),
        "http": _backend_url("HTTP_MCP_URL", "http://http-mcp:8000/mcp"),
        "analysis": _backend_url(
            "ANALYSIS_MCP_URL",
            "http://analysis-mcp:8000/mcp",
        ),
    }


def _proxy(name: str, url: str):
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
    "koba-mcp-gateway",
    version=__version__,
    instructions=(
        "Authenticated edge gateway for isolated Koba MCP runtimes. "
        "GitHub, GitLab, Files, HTTP and analysis execute in private services. "
        "Secrets are never returned as plaintext."
    ),
    auth=_auth,
    middleware=_auth_middleware,
)

github_mcp = _public_facade(
    "koba-github-gateway",
    "github",
    _BACKENDS["github"],
)
gitlab_mcp = _public_facade(
    "koba-gitlab-gateway",
    "gitlab",
    _BACKENDS["gitlab"],
)
files_mcp = _public_facade(
    "koba-files-gateway",
    "files",
    _BACKENDS["files"],
)
http_mcp = _public_facade(
    "koba-http-gateway",
    "http",
    _BACKENDS["http"],
)
analysis_mcp = _public_facade(
    "koba-analysis-gateway",
    "analysis",
    _BACKENDS["analysis"],
)

_mount_aggregate_backends(mcp, _BACKENDS)


@mcp.tool(title="Bridge ping", annotations=READ_ONLY_LOCAL)
def bridge_ping() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "koba-mcp-gateway",
        "version": __version__,
        "time": datetime.now(UTC).isoformat(),
    }


@mcp.tool(title="Bridge build info", annotations=READ_ONLY_LOCAL)
def bridge_build_info() -> dict[str, str]:
    return {
        "service": "koba-mcp-gateway",
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
            "opentelemetry",
            "modular-gateway",
            "infisical-secrets",
            "github-runtime",
            "gitlab-runtime",
            "files-runtime",
            "http-runtime",
            "analysis-runtime",
        ],
        "status": "active",
    }


register_secrets_tools(mcp, READ_EXTERNAL)


def _split_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


_allowed_hosts = _split_env(
    "MCP_ALLOWED_HOSTS",
    "localhost:*,127.0.0.1:*,[::1]:*",
)
_allowed_origins = _split_env(
    "MCP_ALLOWED_ORIGINS",
    "http://localhost:*,http://127.0.0.1:*,http://[::1]:*",
)


def _http_app(surface: FastMCP):
    return surface.http_app(
        path="/mcp",
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    )


app = _http_app(mcp)
app.mount("/github", _http_app(github_mcp))
app.mount("/gitlab", _http_app(gitlab_mcp))
app.mount("/files", _http_app(files_mcp))
app.mount("/http", _http_app(http_mcp))
app.mount("/analysis", _http_app(analysis_mcp))
