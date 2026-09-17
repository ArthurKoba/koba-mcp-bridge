from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from koba_mcp_bridge.github_actions import GitHubActionsClient
from koba_mcp_bridge.github_actions_tools import register_github_actions_tools
from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_collab import GitHubCollabClient
from koba_mcp_bridge.github_reviewer_tools import register_github_reviewer_tools

_AGENT_NAME = "koba-ai-agent[bot]"
_AGENT_EMAIL = "330168119+koba-ai-agent[bot]@users.noreply.github.com"


def _repoint(
    client: GitHubActionsClient,
    branch: str,
    expected_head_sha: str,
    target_sha: str,
    *,
    dry_run: bool = True,
) -> dict[str, object]:
    from koba_mcp_bridge.github_admin import repoint_reserved_branch

    return repoint_reserved_branch(
        client,
        "ArthurKoba/example",
        branch,
        expected_head_sha,
        target_sha,
        dry_run=dry_run,
    )


class ReservedBranchClient(GitHubActionsClient):
    def __init__(self) -> None:
        super().__init__(app_id="4970571", private_key="unused")
        self.production_head = "old"
        self.ref_reads = 0
        self.race_on_second_ref_read = False
        self.github_protected = False
        self.ref_updates: list[dict[str, object]] = []
        self.commits = {
            "old": self._commit("old", "tree-1", "FH8626 Project Agents", "old@invalid"),
            "new": self._commit("new", "tree-1", _AGENT_NAME, _AGENT_EMAIL),
            "bad-tree": self._commit("bad-tree", "tree-2", _AGENT_NAME, _AGENT_EMAIL),
            "bad-identity": self._commit(
                "bad-identity",
                "tree-1",
                "FH8626 Project Agents",
                "fh8626-agents@invalid",
            ),
        }

    @staticmethod
    def _commit(sha: str, tree_sha: str, name: str, email: str) -> dict[str, object]:
        return {
            "sha": sha,
            "message": sha,
            "tree": {"sha": tree_sha},
            "parents": [],
            "author": {"name": name, "email": email, "date": "2026-09-17T10:00:00Z"},
            "committer": {
                "name": name,
                "email": email,
                "date": "2026-09-17T10:00:00Z",
            },
        }

    def _agent_app_identity(self) -> dict[str, object]:
        return {
            "source": "current_agent_app",
            "app_id": "4970571",
            "slug": "koba-ai-agent",
            "login": _AGENT_NAME,
            "id": 330168119,
            "name": _AGENT_NAME,
            "email": _AGENT_EMAIL,
        }

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del repository, allowed_errors
        if method == "GET" and path == "/repos/ArthurKoba/example":
            return 200, {"default_branch": "main"}
        if method == "GET" and path.endswith("/branches/production"):
            return 200, {
                "name": "production",
                "commit": {"sha": self.production_head},
                "protected": self.github_protected,
            }
        if method == "GET" and path.endswith("/branches/main"):
            return 200, {
                "name": "main",
                "commit": {"sha": "new"},
                "protected": self.github_protected,
            }
        if method == "GET" and path.endswith("/git/ref/heads/production"):
            self.ref_reads += 1
            sha = self.production_head
            if self.race_on_second_ref_read and self.ref_reads >= 2:
                sha = "racer"
            return 200, {"object": {"sha": sha}}
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            self.ref_reads += 1
            return 200, {"object": {"sha": "new"}}
        if method == "GET" and "/git/commits/" in path:
            sha = path.rsplit("/", 1)[-1]
            return 200, self.commits[sha]
        if method == "PATCH" and path.endswith("/git/refs/heads/production"):
            assert isinstance(payload, dict)
            self.ref_updates.append(payload)
            self.production_head = str(payload["sha"])
            return 200, {"object": {"sha": self.production_head}}
        raise AssertionError(f"unexpected request: {method} {path}")


def _agent_client() -> ReservedBranchClient:
    return ReservedBranchClient()


def _reviewer_client() -> GitHubCollabClient:
    return GitHubCollabClient(app_id="4978904", private_key="unused")


def test_reserved_branch_repoint_dry_run_preserves_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = ReservedBranchClient()
    result = _repoint(client, "production", "old", "new", dry_run=True)

    assert result["status"] == "ready"
    assert result["old_head_sha"] == "old"
    assert result["new_head_sha"] == "new"
    assert result["tree_sha"] == "tree-1"
    assert result["content_changed"] is False
    assert result["ref_updated"] is False
    assert client.production_head == "old"
    assert not client.ref_updates


def test_reserved_branch_repoint_force_updates_after_second_head_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = ReservedBranchClient()
    result = _repoint(client, "production", "old", "new", dry_run=False)

    assert result["status"] == "updated"
    assert result["ref_updated"] is True
    assert client.ref_updates == [{"sha": "new", "force": True}]
    assert client.production_head == "new"
    assert client.ref_reads == 2


def test_reserved_branch_repoint_rejects_non_reserved_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    with pytest.raises(GitHubAgentError, match="not reserved"):
        _repoint(ReservedBranchClient(), "main", "new", "new")


def test_reserved_branch_repoint_rejects_tree_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    with pytest.raises(GitHubAgentError, match="would change repository content"):
        _repoint(ReservedBranchClient(), "production", "old", "bad-tree")


def test_reserved_branch_repoint_requires_agent_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    with pytest.raises(GitHubAgentError, match="does not use the current Agent App identity"):
        _repoint(ReservedBranchClient(), "production", "old", "bad-identity")


def test_reserved_branch_repoint_rejects_github_protected_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = ReservedBranchClient()
    client.github_protected = True
    with pytest.raises(GitHubAgentError, match="protected by GitHub"):
        _repoint(client, "production", "old", "new")


def test_reserved_branch_repoint_rejects_default_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "main")
    with pytest.raises(GitHubAgentError, match="refuses the repository default branch"):
        _repoint(ReservedBranchClient(), "main", "new", "new")


def test_reserved_branch_repoint_rejects_race_before_force_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = ReservedBranchClient()
    client.race_on_second_ref_read = True
    with pytest.raises(GitHubAgentError, match="changed during repoint"):
        _repoint(client, "production", "old", "new", dry_run=False)
    assert not client.ref_updates
    assert client.production_head == "old"


@pytest.mark.asyncio
async def test_agent_surface_exposes_reserved_branch_admin_tool() -> None:
    mcp = FastMCP("agent-admin-surface")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    write = ToolAnnotations(read_only_hint=False, open_world_hint=True)
    destructive = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        open_world_hint=True,
    )
    register_github_actions_tools(
        mcp,
        _agent_client,
        read_only,
        write,
        destructive,
    )
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert "github_admin_repoint_reserved_branch" in names


@pytest.mark.asyncio
async def test_reviewer_surface_does_not_expose_admin_tool() -> None:
    mcp = FastMCP("reviewer-admin-surface")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    review_write = ToolAnnotations(read_only_hint=False, open_world_hint=True)
    register_github_reviewer_tools(
        mcp,
        _reviewer_client,
        read_only,
        review_write,
    )
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert not any(name.startswith("github_admin_") for name in names)
