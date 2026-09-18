from __future__ import annotations

import base64

import pytest

import koba_mcp_bridge.github_reviewer as github_reviewer
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_collab import GitHubCollabClient
from koba_mcp_bridge.github_reviewer import (
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



def test_reviewer_loads_convention_config_from_infisical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github_reviewer_client_from_env.cache_clear()
    monkeypatch.setattr(
        github_reviewer,
        "resolve_config_secret",
        lambda path, name: {
            ("github/reviewer", "APP_ID"): "888",
            ("github/reviewer", "PRIVATE_KEY_PEM"): "reviewer-pem",
        }[(path, name)],
    )

    client = github_reviewer_client_from_env()

    assert client.app_id == "888"
    assert client.private_key == "reviewer-pem"

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
