from __future__ import annotations

import pytest

import modules.github.github_reviewer as github_reviewer
from common.settings import GitHubPolicySettings
from modules.github.github_agent import GitHubAgentError
from modules.github.github_collab import GitHubCollabClient
from modules.github.github_reviewer import (
    github_reviewer_client,
    github_reviewer_configured,
)


def _policy(*, required_reviewers: tuple[str, ...] = ()) -> GitHubPolicySettings:
    return GitHubPolicySettings(
        protected_branches=frozenset({"main", "master"}),
        required_checks=("test", "docker"),
        required_reviewers=required_reviewers,
    )


class ReviewGateClient(GitHubCollabClient):
    def __init__(self, reviews: list[dict[str, object]]) -> None:
        super().__init__(
            app_id="123",
            private_key="key-material",
            required_reviewers=("koba-ai-reviewer[bot]",),
        )
        self.reviews = [
            {**review, "commit_id": review.get("commit_id", "current-head")}
            for review in reviews
        ]

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
        if method == "GET" and path.endswith("/pulls/7"):
            return 200, {"head": {"sha": "current-head"}}
        if method == "GET" and path.endswith("/reviews?per_page=100"):
            return 200, self.reviews
        raise AssertionError(f"unexpected request: {method} {path}")


def _unused_client() -> GitHubCollabClient:
    return GitHubCollabClient(
        app_id="123",
        private_key="key-material",
    )


def test_reviewer_configured_uses_infisical_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github_reviewer_client.cache_clear()

    def missing(path: str, name: str) -> str:
        del path, name
        raise github_reviewer.SecretError("missing")

    monkeypatch.setattr(github_reviewer, "resolve_config_secret", missing)
    assert github_reviewer_configured() is False

    values = {
        ("github/reviewer", "APP_ID"): "456",
        ("github/reviewer", "PRIVATE_KEY_PEM"): "reviewer-key",
    }
    monkeypatch.setattr(
        github_reviewer,
        "resolve_config_secret",
        lambda path, name: values[(path, name)],
    )
    assert github_reviewer_configured() is True


def test_reviewer_loads_convention_config_from_infisical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github_reviewer_client.cache_clear()
    monkeypatch.setattr(
        github_reviewer,
        "resolve_config_secret",
        lambda path, name: {
            ("github/reviewer", "APP_ID"): "888",
            ("github/reviewer", "PRIVATE_KEY_PEM"): "reviewer-pem",
        }[(path, name)],
    )

    client = github_reviewer_client(_policy())

    assert client.app_id == "888"
    assert client.private_key == "reviewer-pem"


def test_required_independent_reviewer_approval_passes() -> None:
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


def test_required_independent_reviewer_missing_blocks_merge_gate() -> None:
    client = ReviewGateClient([])
    with pytest.raises(GitHubAgentError, match="required independent reviews"):
        client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)


def test_later_request_changes_revokes_previous_approval() -> None:
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


def test_comment_after_approval_does_not_revoke_decisive_state() -> None:
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
    from fastmcp import Client, FastMCP
    from mcp.types import ToolAnnotations

    from modules.github.github_reviewer_tools import register_github_reviewer_tools

    reviewer_mcp = FastMCP("reviewer-surface-test")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    review_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
    register_github_reviewer_tools(
        reviewer_mcp,
        _unused_client,
        read_only,
        review_write,
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
    assert not any("merge_pull" in name for name in names)
    assert not any("create_branch" in name for name in names)
    assert not any("delete_branch" in name for name in names)


def test_reviewer_infisical_failure_preserves_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github_reviewer_client.cache_clear()

    def fail_secret(path: str, name: str) -> str:
        del path, name
        raise github_reviewer.SecretError("Infisical API HTTP 403: denied")

    monkeypatch.setattr(github_reviewer, "resolve_config_secret", fail_secret)

    with pytest.raises(GitHubAgentError, match="Infisical API HTTP 403"):
        github_reviewer._reviewer_app_id()

    with pytest.raises(GitHubAgentError, match="Infisical API HTTP 403"):
        github_reviewer._reviewer_private_key()

