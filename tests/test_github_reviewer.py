from __future__ import annotations

import base64

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_collab import GitHubCollabClient
from koba_mcp_bridge.github_reviewer import (
    GitHubReviewerClient,
    _reviewer_private_key_from_env,
    github_reviewer_client_from_env,
    github_reviewer_configured,
)
from koba_mcp_bridge.github_reviewer_tools import register_github_reviewer_tools


class ReviewGateClient(GitHubCollabClient):
    def __init__(self, reviews: list[dict[str, object]]) -> None:
        super().__init__(
            app_id="123",
            private_key="key-material",
        )
        self.reviews = reviews

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del repository, payload, allowed_errors
        if method == "GET" and path.endswith("/reviews?per_page=100"):
            return 200, self.reviews
        raise AssertionError(f"unexpected request: {method} {path}")


def _unused_client() -> GitHubCollabClient:
    return GitHubCollabClient(
        app_id="123",
        private_key="key-material",
    )


def test_reviewer_config_requires_only_distinct_app_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github_reviewer_client_from_env.cache_clear()
    for name in (
        "GITHUB_REVIEWER_APP_ID",
        "GITHUB_REVIEWER_PRIVATE_KEY",
        "GITHUB_REVIEWER_PRIVATE_KEY_B64",
        "GITHUB_REVIEWER_ALLOWED_REPOSITORIES",
    ):
        monkeypatch.delenv(name, raising=False)

    assert github_reviewer_configured() is False

    monkeypatch.setenv("GITHUB_REVIEWER_APP_ID", "456")
    monkeypatch.setenv("GITHUB_REVIEWER_PRIVATE_KEY", "reviewer-key")
    assert github_reviewer_configured() is True
    client = github_reviewer_client_from_env()
    assert client.app_id == "456"
    assert client.private_key == "reviewer-key"


def test_reviewer_private_key_can_be_loaded_from_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_REVIEWER_PRIVATE_KEY", raising=False)
    material = "reviewer-key-material\nline-two\n"
    monkeypatch.setenv(
        "GITHUB_REVIEWER_PRIVATE_KEY_B64",
        base64.b64encode(material.encode()).decode(),
    )
    assert _reviewer_private_key_from_env() == material


def test_required_independent_reviewer_approval_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "koba-ai-reviewer[bot]")
    client = ReviewGateClient(
        [
            {
                "user": {"login": "koba-ai-reviewer[bot]"},
                "state": "APPROVED",
            }
        ]
    )
    result = client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)
    assert result["status"] == "ok"


def test_required_independent_reviewer_missing_blocks_merge_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "koba-ai-reviewer[bot]")
    client = ReviewGateClient([])
    with pytest.raises(GitHubAgentError, match="required independent reviews"):
        client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)


def test_later_request_changes_revokes_previous_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "koba-ai-reviewer[bot]")
    client = ReviewGateClient(
        [
            {
                "user": {"login": "koba-ai-reviewer[bot]"},
                "state": "APPROVED",
            },
            {
                "user": {"login": "koba-ai-reviewer[bot]"},
                "state": "CHANGES_REQUESTED",
            },
        ]
    )
    with pytest.raises(GitHubAgentError, match="CHANGES_REQUESTED"):
        client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)


def test_comment_after_approval_does_not_revoke_decisive_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "koba-ai-reviewer[bot]")
    client = ReviewGateClient(
        [
            {
                "user": {"login": "koba-ai-reviewer[bot]"},
                "state": "APPROVED",
            },
            {
                "user": {"login": "koba-ai-reviewer[bot]"},
                "state": "COMMENTED",
            },
        ]
    )
    result = client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_reviewer_tool_surface_excludes_development_mutations() -> None:
    reviewer_mcp = FastMCP("reviewer-surface-test")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    review_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
    destructive = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    )
    register_github_reviewer_tools(
        reviewer_mcp,
        _unused_client,  # type: ignore[arg-type]
        read_only,
        review_write,
        destructive,
    )

    async with Client(reviewer_mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert "github_reviewer_list_repositories" in names
    assert "github_reviewer_create_review" in names
    assert "github_reviewer_get_file" in names
    assert "github_reviewer_workflow_runs" in names
    assert not any("put_file" in name for name in names)
    assert not any("delete_file" in name for name in names)
    assert "github_reviewer_merge_pull_request" in names
    assert not any("create_branch" in name for name in names)
    assert not any("delete_branch" in name for name in names)


class ReviewerMergeClient(GitHubReviewerClient):
    def __init__(self, *, approved_sha: str = "head123", unresolved: bool = False) -> None:
        super().__init__(app_id="456", private_key="key")
        self.approved_sha = approved_sha
        self.unresolved = unresolved
        self.merged_payload: dict[str, object] | None = None

    def _app_identity(self) -> dict[str, object]:
        return {"login": "koba-ai-reviewer[bot]"}

    def _assert_allowed(self, repository: str) -> str:
        return repository

    def assert_required_checks(self, repository: str, ref: str) -> dict[str, object]:
        assert ref == "head123"
        return {"repository": repository, "ref": ref, "status": "ok"}

    def list_review_threads(self, repository: str, number: int) -> dict[str, object]:
        del repository, number
        return {
            "threads": [
                {"id": "T1", "resolved": False, "outdated": False}
            ] if self.unresolved else []
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
        if method == "GET" and path.endswith("/pulls/7"):
            return 200, {
                "state": "open",
                "draft": False,
                "head": {
                    "sha": "head123",
                    "repo": {"full_name": "ArthurKoba/koba-mcp-bridge"},
                },
                "base": {
                    "ref": "main",
                    "repo": {"full_name": "ArthurKoba/koba-mcp-bridge"},
                },
            }
        if method == "GET" and path.endswith("/reviews?per_page=100"):
            return 200, [{
                "user": {"login": "koba-ai-reviewer[bot]"},
                "state": "APPROVED",
                "commit_id": self.approved_sha,
            }]
        if method == "PUT" and path.endswith("/merge"):
            assert isinstance(payload, dict)
            self.merged_payload = payload
            return 200, {"merged": True, "sha": "merge456", "message": "merged"}
        raise AssertionError(f"unexpected request: {method} {path}")


def test_reviewer_can_merge_protected_pr_after_current_head_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_PROTECTED_BRANCHES", raising=False)
    client = ReviewerMergeClient()
    result = client.merge_protected_pull_request(
        "ArthurKoba/koba-mcp-bridge", 7, "squash"
    )
    assert result["merged"] is True
    assert client.merged_payload == {"merge_method": "squash", "sha": "head123"}


def test_reviewer_rejects_stale_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_PROTECTED_BRANCHES", raising=False)
    client = ReviewerMergeClient(approved_sha="oldsha")
    with pytest.raises(GitHubAgentError, match="approval is stale"):
        client.merge_protected_pull_request("ArthurKoba/koba-mcp-bridge", 7)


def test_reviewer_rejects_unresolved_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_PROTECTED_BRANCHES", raising=False)
    client = ReviewerMergeClient(unresolved=True)
    with pytest.raises(GitHubAgentError, match="unresolved review threads"):
        client.merge_protected_pull_request("ArthurKoba/koba-mcp-bridge", 7)
