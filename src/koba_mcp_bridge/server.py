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


def _required_backend_url(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _configured_backends() -> dict[str, dict[str, str]]:
    return {
        "github": {
            "url": _required_backend_url("GITHUB_MCP_URL"),
            "namespace": "",
        },
        "files": {
            "url": _required_backend_url("FILES_MCP_URL"),
            "namespace": "",
        },
        "http": {
            "url": _required_backend_url("HTTP_MCP_URL"),
            "namespace": "",
        },
        "analysis": {
            "url": _required_backend_url("ANALYSIS_MCP_URL"),
            "namespace": "",
        },
    }


def _mount_backends(server: FastMCP) -> dict[str, dict[str, str]]:
    backends = _configured_backends()
    for name, config in backends.items():
        proxy = create_proxy(
            config["url"],
            name=f"{name}-backend",
            mode="auto",
        )
        server.mount(server=proxy)
    return backends


_auth, _auth_middleware = _build_auth()

mcp = FastMCP(
    "koba-mcp-bridge",
    version=__version__,
    instructions=(
        "Koba MCP Bridge is the authenticated gateway for Koba infrastructure, "
        "local tools, and mounted MCP backends. Files are first-class immutable "
        "files identified by file_id. For client/chat attachments, prefer "
        "file_ingest so the client can hand Koba an authorized file URL and "
        "Koba can stream the bytes directly without model-visible base64. Use "
        "file_upload_* only as the generic resumable fallback. Backend-specific "
        "adapters such as ghidra_import_file consume file_id. Filesystem paths "
        "are private server implementation details and are never cross-service identifiers."
    ),
    auth=_auth,
    middleware=_auth_middleware,
)


gitlab_mcp = FastMCP(
    "koba-gitlab",
    version=__version__,
    instructions=(
        "Dedicated GitLab connector surface. Every operation requires an explicit "
        "profile_id selecting one GitLab instance and credential identity. Profiles "
        "never contain inline tokens; credentials come from runtime secret env vars "
        "or mounted secret files."
    ),
    auth=_auth,
    middleware=_auth_middleware,
)
if _gateway_mode() == "embedded":
    register_gitlab_tools(
        gitlab_mcp,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
        DESTRUCTIVE_EXTERNAL,
    )
else:
    gitlab_url = os.getenv("GITLAB_MCP_URL", "").strip()
    if not gitlab_url:
        raise RuntimeError(
            "GITLAB_MCP_URL is required when KOBA_GATEWAY_MODE=proxy"
        )
    gitlab_proxy = create_proxy(
        gitlab_url,
        name="gitlab-backend",
        mode="auto",
    )
    gitlab_mcp.mount(server=gitlab_proxy)

mcp.mount(gitlab_mcp, namespace="gitlab")


@mcp.tool(
    title="Bridge ping",
    annotations=READ_ONLY_LOCAL,
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
    annotations=READ_ONLY_LOCAL,
)
def bridge_build_info() -> dict[str, str]:
    """Return build metadata for the currently running bridge instance."""
    return {
        "service": "koba-mcp-bridge",
        "version": __version__,
        "commit": os.getenv("BUILD_SHA", "unknown"),
        "built_at": os.getenv("BUILD_TIME", "unknown"),
        "started_at": _STARTED_AT,
        "python": platform.python_version(),
    }


@mcp.tool(
    title="Bridge capabilities",
    annotations=READ_ONLY_LOCAL,
)
def bridge_capabilities() -> dict[str, object]:
    """Return the currently enabled high-level bridge capabilities."""
    features = [
        "mcp",
        "streamable-http",
        "opentelemetry",
        "gateway",
        "file-store-v2",
        "agent-resumable-upload",
        "attachment-file-ingress",
        "file-collections",
        "file-references",
        "infisical-secrets",
        "secret-references",
        "curl-http-client",
        "curl-file-download",
        "curl-stream-capture",
        "curl-browser-header-presets",
        "gitlab-multi-profile",
        "gitlab-dedicated-endpoint",
        "gitlab-repository-workflow",
        "gitlab-merge-requests",
        "gitlab-ci",
    ]
    if _auth is not None:
        features.append("github-oauth")
    if github_agent_configured():
        features.extend(
            [
                "github-app-agent",
                "github-development-workflow",
                "github-rebase-review",
                "github-review-threads",
                "github-actions-diagnostics",
                "github-installation-repository-discovery",
            ]
        )
    if github_reviewer_configured():
        features.append("github-independent-reviewer")
    return {
        "gateway_mode": _gateway_mode(),
        "backends": sorted(_MOUNTED_BACKENDS),
        "workers": [],
        "features": features,
        "status": "active",
    }


if _gateway_mode() == "embedded":
    register_github_core_tools(
        mcp,
        _github_agent_client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
        DESTRUCTIVE_EXTERNAL,
    )
    register_github_workflow_tools(
        mcp,
        _github_agent_client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
        DESTRUCTIVE_EXTERNAL,
    )
    register_github_review_tools(
        mcp,
        _github_agent_client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
    )
    register_github_collab_tools(
        mcp,
        _github_agent_client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
    )
    register_github_actions_tools(
        mcp,
        _github_agent_client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
        DESTRUCTIVE_EXTERNAL,
    )
    register_file_tools(mcp, READ_ONLY_LOCAL, WRITE_LOCAL, DESTRUCTIVE_LOCAL)
    register_curl_tools(mcp, READ_ONLY_LOCAL, WRITE_EXTERNAL)

register_secrets_tools(mcp, READ_EXTERNAL)
register_reverse_workflow_tools(mcp, READ_ONLY_LOCAL, WRITE_LOCAL)

if _gateway_mode() == "embedded" and github_reviewer_configured():
    register_github_reviewer_tools(
        mcp,
        github_reviewer_client_from_env,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
    )


def _split_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


_MOUNTED_BACKENDS = _mount_backends(mcp)

_allowed_hosts = _split_env(
    "MCP_ALLOWED_HOSTS",
    "localhost:*,127.0.0.1:*,[::1]:*",
)
_allowed_origins = _split_env(
    "MCP_ALLOWED_ORIGINS",
    "http://localhost:*,http://127.0.0.1:*,http://[::1]:*",
)

app = mcp.http_app(
    path="/mcp",
    allowed_hosts=_allowed_hosts,
    allowed_origins=_allowed_origins,
)

gitlab_app = gitlab_mcp.http_app(
    path="/mcp",
    allowed_hosts=_allowed_hosts,
    allowed_origins=_allowed_origins,
)
app.mount("/gitlab", gitlab_app)
