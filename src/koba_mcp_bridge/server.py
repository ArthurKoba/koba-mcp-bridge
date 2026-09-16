from __future__ import annotations

import base64
import json
import os
import platform
import urllib.error
import urllib.request
from datetime import UTC, datetime
from functools import lru_cache
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware
from mcp.types import ToolAnnotations

from . import __version__
from .github_agent import github_agent_configured
from .github_tools import register_github_workflow_tools
from .github_workflow import GitHubDevClient

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
_DESTRUCTIVE_EXTERNAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)
_CHATGPT_OAUTH_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
_DEFAULT_GITHUB_PROBE_REPOSITORY = "ArthurKoba/koba-mcp-bridge"
_DEFAULT_GITHUB_PROBE_BRANCH = "mcp-write-probe"


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


def _github_write_probe_target() -> tuple[str, str]:
    repository = os.getenv(
        "GITHUB_WRITE_PROBE_REPOSITORY",
        _DEFAULT_GITHUB_PROBE_REPOSITORY,
    ).strip()
    branch = os.getenv("GITHUB_WRITE_PROBE_BRANCH", _DEFAULT_GITHUB_PROBE_BRANCH).strip()
    if not repository or "/" not in repository:
        raise RuntimeError("GITHUB_WRITE_PROBE_REPOSITORY must be owner/repository")
    if not branch:
        raise RuntimeError("GITHUB_WRITE_PROBE_BRANCH must not be empty")
    return repository, branch


def _github_write_probe_request(token: str, repository: str, branch: str) -> dict[str, object]:
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = f".mcp-write-probes/{stamp}-{uuid4().hex}.txt"
    text = (
        "Koba MCP Bridge browser write probe\n"
        f"created_at={now.isoformat()}\n"
        f"repository={repository}\n"
        f"branch={branch}\n"
    )
    payload = json.dumps(
        {
            "message": f"test: browser MCP write probe {stamp}",
            "content": base64.b64encode(text.encode()).decode(),
            "branch": branch,
        }
    ).encode()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/contents/{path}",
        data=payload,
        method="PUT",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "koba-mcp-bridge",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode())
            return {
                "status": response.status,
                "repository": repository,
                "branch": branch,
                "path": path,
                "commit_sha": str(result.get("commit", {}).get("sha", "")),
                "content_sha": str(result.get("content", {}).get("sha", "")),
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read(1024).decode("utf-8", "replace")
        raise RuntimeError(f"GitHub write probe failed with HTTP {exc.code}: {detail}") from exc


@lru_cache(maxsize=1)
def _github_agent_client() -> GitHubDevClient:
    return GitHubDevClient.from_env()


_auth, _auth_middleware = _build_auth()

mcp = FastMCP(
    "koba-mcp-bridge",
    version=__version__,
    instructions=(
        "Koba MCP Bridge is the authenticated gateway for Koba infrastructure, "
        "local tools, and mounted MCP backends."
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
    features = ["mcp", "streamable-http", "opentelemetry", "gateway"]
    if _auth is not None:
        features.append("github-oauth")
    if os.getenv("GITHUB_WRITE_PROBE_TOKEN", "").strip():
        features.append("github-write-probe")
    if github_agent_configured():
        features.extend(["github-app-agent", "github-development-workflow"])
    return {
        "backends": sorted(_MOUNTED_BACKENDS),
        "workers": [],
        "features": features,
        "status": "active",
    }


@mcp.tool(
    title="GitHub browser write probe",
    annotations=_WRITE_EXTERNAL,
)
def github_write_probe() -> dict[str, object]:
    """Create one unique test file in the configured GitHub probe branch.

    This is intentionally a write/mutation tool for testing whether browser ChatGPT is allowed
    to invoke a custom MCP action with external side effects. The target repository and branch
    are controlled only by server-side environment variables; callers cannot choose them.
    """
    token = os.getenv("GITHUB_WRITE_PROBE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_WRITE_PROBE_TOKEN is not configured")
    repository, branch = _github_write_probe_target()
    return _github_write_probe_request(token, repository, branch)


@mcp.tool(title="GitHub agent status", annotations=_READ_EXTERNAL)
def github_agent_status(repository: str) -> dict[str, object]:
    """Verify GitHub App installation access to one allowlisted repository."""
    return _github_agent_client().status(repository)


@mcp.tool(title="GitHub agent get file", annotations=_READ_EXTERNAL)
def github_agent_get_file(repository: str, path: str, ref: str | None = None) -> dict[str, object]:
    """Read one UTF-8 repository file from an allowlisted GitHub repository."""
    return _github_agent_client().get_file(repository, path, ref)


@mcp.tool(title="GitHub agent list branches", annotations=_READ_EXTERNAL)
def github_agent_list_branches(repository: str) -> dict[str, object]:
    """List branches in one allowlisted GitHub repository."""
    return _github_agent_client().list_branches(repository)


@mcp.tool(title="GitHub agent create branch", annotations=_WRITE_EXTERNAL)
def github_agent_create_branch(
    repository: str,
    branch: str,
    from_branch: str = "main",
) -> dict[str, object]:
    """Create a new branch from an existing branch in an allowlisted repository."""
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
    """Compare two branches, tags, or commit refs in an allowlisted repository."""
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
