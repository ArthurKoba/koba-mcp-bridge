from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from github_mcp.github_actions import GitHubActionsClient
from github_mcp.github_actions_tools import register_github_actions_tools
from github_mcp.github_agent import GitHubAgentError
from github_mcp.github_collab import GitHubCollabClient
from github_mcp.github_reviewer_tools import register_github_reviewer_tools


class RecordingHistoryClient(GitHubActionsClient):
    def __init__(self) -> None:
        super().__init__(app_id="4970571", private_key="unused")
        self.head = "c3"
        self.ref_reads = 0
        self.race_on_second_ref_read = False
        self.created: dict[str, dict[str, object]] = {}
        self.created_payloads: list[dict[str, object]] = []
        self.ref_updates: list[dict[str, object]] = []
        self.deleted_refs: list[str] = []
        self.source = {
            "c1": self._git_commit(
                "c1",
                "t1",
                "one",
                [],
                "2026-09-17T10:00:00Z",
            ),
            "c2": self._git_commit(
                "c2",
                "t2",
                "two",
                ["c1"],
                "2026-09-17T11:00:00Z",
            ),
            "c3": self._git_commit(
                "c3",
                "t3",
                "three",
                ["c2"],
                "2026-09-17T12:00:00Z",
            ),
        }

    @staticmethod
    def _git_commit(
        sha: str,
        tree_sha: str,
        message: str,
        parents: list[str],
        date: str,
    ) -> dict[str, object]:
        return {
            "sha": sha,
            "message": message,
            "tree": {"sha": tree_sha},
            "parents": [{"sha": parent} for parent in parents],
            "author": {
                "name": "FH8626 Project Agents",
                "email": "fh8626-agents@invalid",
                "date": date,
            },
            "committer": {
                "name": "FH8626 Project Agents",
                "email": "fh8626-agents@invalid",
                "date": date,
            },
        }

    @staticmethod
    def _rest_commit() -> dict[str, object]:
        return {
            "sha": "c3",
            "commit": {
                "message": "three",
                "tree": {"sha": "t3"},
                "author": {
                    "name": "koba-ai-agent[bot]",
                    "email": (
                        "330168119+koba-ai-agent[bot]@users.noreply.github.com"
                    ),
                    "date": "2026-09-17T12:00:00Z",
                },
                "committer": {
                    "name": "koba-ai-agent[bot]",
                    "email": (
                        "330168119+koba-ai-agent[bot]@users.noreply.github.com"
                    ),
                    "date": "2026-09-17T12:00:00Z",
                },
                "verification": {
                    "verified": False,
                    "reason": "unsigned",
                    "signature": None,
                    "payload": None,
                    "verified_at": None,
                },
            },
            "author": {
                "login": "koba-ai-agent[bot]",
                "id": 330168119,
                "type": "Bot",
            },
            "committer": {
                "login": "koba-ai-agent[bot]",
                "id": 330168119,
                "type": "Bot",
            },
            "parents": [{"sha": "c2"}],
            "files": [
                {
                    "filename": "README.md",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "patch": "@@",
                }
            ],
        }

    def _app_jwt(self) -> str:
        return "app-jwt"

    def _installation_id(self, repository: str) -> int:
        del repository
        return 77

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del token, payload, allowed_errors
        if method == "GET" and url.endswith("/app"):
            return 200, {"slug": "koba-ai-agent"}
        if method == "GET" and "/users/koba-ai-agent%5Bbot%5D" in url:
            return 200, {"id": 330168119, "login": "koba-ai-agent[bot]"}
        if method == "POST" and url.endswith("/app/installations/77/access_tokens"):
            return 201, {
                "permissions": {
                    "contents": "write",
                    "pull_requests": "write",
                    "issues": "write",
                    "actions": "write",
                    "checks": "read",
                }
            }
        raise AssertionError(f"unexpected request: {method} {url}")

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
        if method == "GET" and path.endswith("/branches?per_page=100"):
            return 200, [
                {"name": "main", "commit": {"sha": self.head}, "protected": False},
                {"name": "production", "commit": {"sha": "p1"}, "protected": False},
            ]
        if method == "GET" and "/branches/" in path:
            branch = path.rsplit("/", 1)[-1]
            return 200, {
                "name": branch,
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
        if method == "DELETE" and "/git/refs/heads/" in path:
            self.deleted_refs.append(path)
            return 204, {}
        if method == "GET" and "/commits?" in path:
            return 200, [self._rest_commit()]
        if method == "GET" and path.endswith("/commits/c3"):
            return 200, self._rest_commit()
        if method == "GET" and path.endswith("/repos/ArthurKoba/example"):
            return 200, {
                "full_name": "ArthurKoba/example",
                "default_branch": "main",
                "fork": False,
                "archived": False,
            }
        raise AssertionError(f"unexpected request: {method} {path}")


def _agent_client() -> RecordingHistoryClient:
    return RecordingHistoryClient()


def _reviewer_client() -> GitHubCollabClient:
    return GitHubCollabClient(app_id="4978904", private_key="unused")


def test_branch_observability_distinguishes_bridge_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = RecordingHistoryClient()
    result = client.list_branches("ArthurKoba/example")
    branches = {item["name"]: item for item in result["branches"]}

    assert branches["main"]["github_protected"] is False
    assert branches["main"]["bridge_reserved"] is False
    assert branches["main"]["mutation_allowed"] is True
    assert branches["production"]["github_protected"] is False
    assert branches["production"]["bridge_reserved"] is True
    assert branches["production"]["mutation_allowed"] is False
    assert branches["production"]["mutation_denial_reason"] == (
        "branch is reserved by bridge mutation policy"
    )

    with pytest.raises(GitHubAgentError, match="reserved by bridge mutation policy"):
        client.delete_branch("ArthurKoba/example", "production")


def test_commit_observability_includes_git_and_github_identity() -> None:
    client = RecordingHistoryClient()
    listed = client.list_commits("ArthurKoba/example", ref="main")
    commit = listed["commits"][0]
    assert commit["author"]["name"] == "koba-ai-agent[bot]"
    assert commit["author"]["login"] == "koba-ai-agent[bot]"
    assert commit["committer"]["email"].endswith("@users.noreply.github.com")
    assert commit["verification"]["reason"] == "unsigned"

    detailed = client.get_commit("ArthurKoba/example", "c3")
    assert detailed["tree_sha"] == "t3"
    assert detailed["author"]["id"] == 330168119
    assert detailed["committer"]["login"] == "koba-ai-agent[bot]"
    assert detailed["verification"]["signature_present"] is False


def test_capabilities_report_permissions_identity_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = RecordingHistoryClient()
    result = client.capabilities("ArthurKoba/example", reviewer_available=True)

    assert result["allowed_repository"] is True
    assert result["permissions"]["contents"] == "write"
    assert result["permissions"]["workflows"] == "none"
    assert result["capabilities"]["force_ref_update"] is True
    assert result["capabilities"]["history_identity_rewrite"] is True
    assert result["agent_identity"]["login"] == "koba-ai-agent[bot]"
    assert result["bridge_policy"]["reserved_branches"] == ["production"]
    assert result["reviewer_available"] is True


def test_rewrite_dry_run_builds_mapping_without_moving_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = RecordingHistoryClient()
    result = client.rewrite_branch_identity(
        "ArthurKoba/example",
        "main",
        "c3",
        dry_run=True,
    )

    assert result["commit_count"] == 3
    assert result["mapping"] == {"c1": "n1", "c2": "n2", "c3": "n3"}
    assert result["new_head_sha"] == "n3"
    assert result["final_tree_sha"] == "t3"
    assert result["ref_updated"] is False
    assert result["dry_run_creates_unreferenced_commit_objects"] is True
    assert client.head == "c3"
    assert not client.ref_updates
    assert [payload["message"] for payload in client.created_payloads] == [
        "one",
        "two",
        "three",
    ]
    assert [payload["tree"] for payload in client.created_payloads] == ["t1", "t2", "t3"]
    assert all(
        payload["author"]["name"] == "koba-ai-agent[bot]"
        and payload["committer"]["name"] == "koba-ai-agent[bot]"
        for payload in client.created_payloads
    )


def test_rewrite_force_updates_once_after_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = RecordingHistoryClient()
    result = client.rewrite_branch_identity(
        "ArthurKoba/example",
        "main",
        "c3",
        dry_run=False,
    )

    assert result["ref_updated"] is True
    assert result["old_head_sha"] == "c3"
    assert result["new_head_sha"] == "n3"
    assert result["old_shas_reachable_from_new_head"] is False
    assert client.ref_updates == [{"sha": "n3", "force": True}]
    assert client.head == "n3"


def test_rewrite_rejects_head_race_before_force_ref_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = RecordingHistoryClient()
    client.race_on_second_ref_read = True

    with pytest.raises(GitHubAgentError, match="changed during rewrite"):
        client.rewrite_branch_identity(
            "ArthurKoba/example",
            "main",
            "c3",
            dry_run=False,
        )

    assert not client.ref_updates
    assert client.head == "c3"


def test_rewrite_requires_expected_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "production")
    client = RecordingHistoryClient()
    with pytest.raises(GitHubAgentError, match="expected_head_sha is required"):
        client.rewrite_branch_identity(
            "ArthurKoba/example",
            "main",
            "",
            dry_run=True,
        )


@pytest.mark.asyncio
async def test_agent_surface_exposes_history_tools() -> None:
    mcp = FastMCP("agent-history-surface")
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
    assert "github_agent_capabilities" in names
    assert "github_agent_rewrite_branch_identity" in names


@pytest.mark.asyncio
async def test_reviewer_surface_does_not_expose_history_mutation() -> None:
    mcp = FastMCP("reviewer-history-surface")
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
    assert not any("rewrite" in name for name in names)
    assert not any("force_ref" in name for name in names)
