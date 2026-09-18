from __future__ import annotations

import os
import platform
from datetime import UTC, datetime
from functools import lru_cache

from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware
from mcp.types import ToolAnnotations

from . import __version__
from .artifact_tools import register_artifact_tools
from .curl_mcp_tools import register_curl_tools
from .github_actions_tools import register_github_actions_tools
from .github_agent import github_agent_configured
from .github_collab_tools import register_github_collab_tools
from .github_identity import GitHubPrettyIdentityClient
from .github_review_tools import register_github_review_tools
from .github_reviewer import github_reviewer_client_from_env, github_reviewer_configured
from .github_reviewer_tools import register_github_reviewer_tools
from .github_tools import register_github_workflow_tools
from .reverse_workflow import register_reverse_workflow_tools

_STARTED_AT = datetime.now(UTC).isoformat()
_READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=False,
)
_READ_EXTERNAL = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=True,
)
_WRITE_EXTERNAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
_WRITE_LOCAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
_DESTRUCTIVE_EXTERNAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)
_DESTRUCTIVE_LOCAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)
_CHATGPT_OAUTH_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"


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
    raw = _required_env("OAUTH_ALLOWED_GITHUB_USERS")
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
        client_id=_required_env("OAUTH_GITHUB_CLIENT_ID"),
        client_secret=_required_env("OAUTH_GITHUB_CLIENT_SECRET"),
        base_url=os.getenv("OAUTH_BASE_URL", "https://mcp.koba-nexus.ru"),
        required_scopes=["read:user"],
        jwt_signing_key=_required_env("OAUTH_JWT_SIGNING_KEY"),
        allowed_client_redirect_uris=[_CHATGPT_OAUTH_REDIRECT],
        require_authorization_consent="external",
        enable_cimd=False,
        fallback_refresh_token_expiry_seconds=30 * 24 * 60 * 60,
        fastmcp_access_token_expiry_seconds=30 * 60,
    )
    return provider, [AuthMiddleware(auth=_github_user_allowed)]


def _configured_backends() -> dict[str, str]:
    backends: dict[str, str] = {}
    ghidra_url = os.getenv("GHIDRA_MCP_URL", "").strip()
    if ghidra_url:
        backends["ghidra"] = ghidra_url
    return backends


def _mount_backends(server: FastMCP) -> dict[str, str]:
    backends = _configured_backends()
    for namespace, url in backends.items():
        proxy = create_proxy(url, name=f"{namespace}-backend", mode="auto")
        server.mount(server=proxy, namespace=namespace)
    return backends


@lru_cache(maxsize=1)
def _github_agent_client() -> GitHubPrettyIdentityClient:
    return GitHubPrettyIdentityClient.from_env()


_auth, _auth_middleware = _build_auth()

mcp = FastMCP(
    "koba-mcp-bridge",
    version=__version__,
    instructions=(
        "Koba MCP Bridge is the authenticated gateway for Koba infrastructure, "
        "local tools, and mounted MCP backends. Files are first-class immutable "
        "artifacts identified by artifact_id. For client/chat attachments, prefer "
        "artifact_ingest_file so the client can hand Koba an authorized file URL and "
        "Koba can stream the bytes directly without model-visible base64. Use "
        "artifact_upload_* only as the generic resumable fallback. Backend-specific "
        "adapters such as ghidra_import_artifact consume artifact_id. Filesystem paths "
        "are private server implementation details and are never cross-service identifiers."
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
        "commit": os.getenv("BUILD_SHA", "unknown"),
        "built_at": os.getenv("BUILD_TIME", "unknown"),
        "started_at": _STARTED_AT,
        "python": platform.python_version(),
    }


@mcp.tool(
    title="Bridge capabilities",
    annotations=_READ_ONLY_LOCAL,
)
def bridge_capabilities() -> dict[str, object]:
    """Return the currently enabled high-level bridge capabilities."""
    features = [
        "mcp",
        "streamable-http",
        "opentelemetry",
        "gateway",
        "artifact-store-v2",
        "agent-resumable-upload",
        "attachment-file-ingress",
        "artifact-collections",
        "artifact-references",
        "curl-http-client",
        "curl-artifact-download",
        "curl-stream-capture",
        "curl-browser-header-presets",
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
        "backends": sorted(_MOUNTED_BACKENDS),
        "workers": [],
        "features": features,
        "status": "active",
    }


@mcp.tool(title="GitHub agent list repositories", annotations=_READ_EXTERNAL)
def github_agent_list_repositories() -> dict[str, object]:
    """List repositories currently granted to the development GitHub App installation."""
    return _github_agent_client().list_repositories()


@mcp.tool(title="GitHub agent status", annotations=_READ_EXTERNAL)
def github_agent_status(repository: str) -> dict[str, object]:
    """Verify development GitHub App installation access to one repository."""
    return _github_agent_client().status(repository)


@mcp.tool(title="GitHub agent get file", annotations=_READ_EXTERNAL)
def github_agent_get_file(repository: str, path: str, ref: str | None = None) -> dict[str, object]:
    """Read one UTF-8 repository file through the development GitHub App."""
    return _github_agent_client().get_file(repository, path, ref)


@mcp.tool(title="GitHub agent list branches", annotations=_READ_EXTERNAL)
def github_agent_list_branches(repository: str) -> dict[str, object]:
    """List branches in a repository installed for the development GitHub App."""
    return _github_agent_client().list_branches(repository)


@mcp.tool(title="GitHub agent create branch", annotations=_WRITE_EXTERNAL)
def github_agent_create_branch(
    repository: str,
    branch: str,
    from_branch: str = "main",
) -> dict[str, object]:
    """Create a new branch from an existing branch in an installed repository."""
    return _github_agent_client().create_branch(repository, branch, from_branch)


@mcp.tool(title="GitHub agent put file", annotations=_WRITE_EXTERNAL)
def github_agent_put_file(
    repository: str,
    path: str,
    content: str,
    message: str,
    branch: str,
) -> dict[str, object]:
    """Create or fully replace one UTF-8 file on a non-protected branch."""
    return _github_agent_client().put_file(repository, path, content, message, branch)


@mcp.tool(title="GitHub agent delete file", annotations=_DESTRUCTIVE_EXTERNAL)
def github_agent_delete_file(
    repository: str,
    path: str,
    message: str,
    branch: str,
) -> dict[str, object]:
    """Delete one file and commit the deletion on a non-protected branch."""
    return _github_agent_client().delete_file(repository, path, message, branch)


@mcp.tool(title="GitHub agent compare refs", annotations=_READ_EXTERNAL)
def github_agent_compare(repository: str, base: str, head: str) -> dict[str, object]:
    """Compare two branches, tags, or commit refs in an installed repository."""
    return _github_agent_client().compare(repository, base, head)


@mcp.tool(title="GitHub agent fast-forward branch", annotations=_WRITE_EXTERNAL)
def github_agent_fast_forward(
    repository: str,
    branch: str,
    to_ref: str,
) -> dict[str, object]:
    """Fast-forward a non-protected branch to another ref without force updates."""
    return _github_agent_client().fast_forward(repository, branch, to_ref)


register_github_workflow_tools(
    mcp,
    _github_agent_client,
    _READ_EXTERNAL,
    _WRITE_EXTERNAL,
    _DESTRUCTIVE_EXTERNAL,
)
register_github_review_tools(
    mcp,
    _github_agent_client,
    _READ_EXTERNAL,
    _WRITE_EXTERNAL,
)
register_github_collab_tools(
    mcp,
    _github_agent_client,
    _READ_EXTERNAL,
    _WRITE_EXTERNAL,
)
register_github_actions_tools(
    mcp,
    _github_agent_client,
    _READ_EXTERNAL,
    _WRITE_EXTERNAL,
    _DESTRUCTIVE_EXTERNAL,
)
register_artifact_tools(mcp, _READ_ONLY_LOCAL, _WRITE_LOCAL, _DESTRUCTIVE_LOCAL)
register_curl_tools(mcp, _READ_ONLY_LOCAL, _WRITE_EXTERNAL)
register_reverse_workflow_tools(mcp, _READ_ONLY_LOCAL, _WRITE_LOCAL)

if github_reviewer_configured():
    register_github_reviewer_tools(
        mcp,
        github_reviewer_client_from_env,
        _READ_EXTERNAL,
        _WRITE_EXTERNAL,
    )


def _split_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


_MOUNTED_BACKENDS = _mount_backends(mcp)

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
