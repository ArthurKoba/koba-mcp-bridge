from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from modules.github.github_actions import GitHubActionsClient
from modules.github.github_actions_tools import register_github_actions_tools
from modules.github.github_agent import GitHubAgentError
from modules.github.github_history_graph import rewrite_branch_identity_graph

_AGENT_NAME = "Koba AI Agent"
_AGENT_EMAIL = "330168119+koba-ai-agent[bot]@users.noreply.github.com"


class RecordingGraphClient(GitHubActionsClient):
    def __init__(self) -> None:
        super().__init__(
            app_id="4970571",
            private_key="unused",
            protected_branches=frozenset({"production"}),
        )
        self.head = "h"
        self.ref_reads = 0
        self.race_on_second_ref_read = False
        self.created: dict[str, dict[str, object]] = {}
        self.created_payloads: list[dict[str, object]] = []
        self.ref_updates: list[dict[str, object]] = []
        self.source = {
            "a": self._commit("a", "ta", "root", []),
            "b": self._commit("b", "tb", "left", ["a"]),
            "c": self._commit("c", "tc", "right", ["a"]),
            "m": self._commit("m", "tm", "merge", ["b", "c"]),
            "h": self._commit("h", "th", "head", ["m"]),
        }

    @staticmethod
    def _commit(
        sha: str,
        tree_sha: str,
        message: str,
        parents: list[str],
    ) -> dict[str, object]:
        return {
            "sha": sha,
            "message": message,
            "tree": {"sha": tree_sha},
            "parents": [{"sha": parent} for parent in parents],
            "author": {
                "name": "ArthurKoba",
                "email": "61914203+ArthurKoba@users.noreply.github.com",
                "date": "2026-09-17T10:00:00Z",
            },
            "committer": {
                "name": "GitHub",
                "email": "noreply@github.com",
                "date": "2026-09-17T10:00:00Z",
            },
        }

    def _agent_app_identity(self) -> dict[str, object]:
        return {
            "source": "current_agent_app",
            "app_id": "4970571",
            "slug": "koba-ai-agent",
            "display_name": _AGENT_NAME,
            "login": "koba-ai-agent[bot]",
            "id": 330168119,
            "type": "Bot",
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
        if method == "GET" and path.endswith("/branches/main"):
            return 200, {
                "name": "main",
                "commit": {"sha": self.head},
                "protected": False,
            }
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            self.ref_reads += 1
            sha = self.head
            if self.race_on_second_ref_read and self.ref_reads >= 2:
                sha = "racer"
            return 200, {"object": {"sha": sha}}
        if method == "GET" and "/git/commits/" in path:
            sha = path.rsplit("/", 1)[-1]
            if sha in self.created:
                return 200, self.created[sha]
            return 200, self.source[sha]
        if method == "POST" and path.endswith("/git/commits"):
            assert isinstance(payload, dict)
            self.created_payloads.append(payload)
            sha = f"n{len(self.created_payloads)}"
            created = {
                "sha": sha,
                "message": payload["message"],
                "tree": {"sha": payload["tree"]},
                "parents": [
                    {"sha": parent}
                    for parent in payload.get("parents", [])
                ],
                "author": dict(payload["author"]),
                "committer": dict(payload["committer"]),
            }
            self.created[sha] = created
            return 201, created
        if method == "PATCH" and path.endswith("/git/refs/heads/main"):
            assert isinstance(payload, dict)
            self.ref_updates.append(payload)
            self.head = str(payload["sha"])
            return 200, {"object": {"sha": self.head}}
        raise AssertionError(f"unexpected request: {method} {path}")


def _agent_client(_account_id: str) -> RecordingGraphClient:
    return RecordingGraphClient()


def test_graph_rewrite_dry_run_preserves_merge_topology() -> None:
    client = RecordingGraphClient()

    result = rewrite_branch_identity_graph(
        client,
        "ArthurKoba/example",
        "main",
        "h",
        dry_run=True,
    )

    assert result["commit_count"] == 5
    assert result["merge_commit_count"] == 1
    assert result["final_tree_sha"] == "th"
    assert result["ref_updated"] is False
    assert result["identity"]["name"] == _AGENT_NAME
    mapping = result["mapping"]
    assert isinstance(mapping, dict)
    merge_payload = client.created_payloads[3]
    assert merge_payload["message"] == "merge"
    assert merge_payload["parents"] == [mapping["b"], mapping["c"]]
    assert all(payload["author"]["name"] == _AGENT_NAME for payload in client.created_payloads)
    assert all(payload["committer"]["email"] == _AGENT_EMAIL for payload in client.created_payloads)
    assert client.head == "h"
    assert not client.ref_updates


def test_graph_rewrite_force_updates_once_after_validation() -> None:
    client = RecordingGraphClient()

    result = rewrite_branch_identity_graph(
        client,
        "ArthurKoba/example",
        "main",
        "h",
        dry_run=False,
    )

    assert result["ref_updated"] is True
    assert result["old_head_sha"] == "h"
    assert result["new_head_sha"] == "n5"
    assert client.ref_updates == [{"sha": "n5", "force": True}]
    assert client.head == "n5"
    assert client.ref_reads == 2


def test_graph_rewrite_rejects_head_race() -> None:
    client = RecordingGraphClient()
    client.race_on_second_ref_read = True

    with pytest.raises(GitHubAgentError, match="changed during graph rewrite"):
        rewrite_branch_identity_graph(
            client,
            "ArthurKoba/example",
            "main",
            "h",
            dry_run=False,
        )

    assert not client.ref_updates
    assert client.head == "h"


def test_graph_rewrite_enforces_max_commits() -> None:
    with pytest.raises(GitHubAgentError, match="exceeds max_commits=3"):
        rewrite_branch_identity_graph(
            RecordingGraphClient(),
            "ArthurKoba/example",
            "main",
            "h",
            max_commits=3,
        )


@pytest.mark.asyncio
async def test_agent_surface_exposes_graph_rewrite() -> None:
    mcp = FastMCP("agent-graph-history-surface")
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
    assert "github_agent_rewrite_branch_identity_graph" in names
