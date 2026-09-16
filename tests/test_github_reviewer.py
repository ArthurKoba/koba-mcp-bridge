from __future__ import annotations

import base64

import pytest

from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_collab import GitHubCollabClient
from koba_mcp_bridge.github_reviewer import (
    _reviewer_allowed_repositories_from_env,
    _reviewer_private_key_from_env,
    github_reviewer_client_from_env,
    github_reviewer_configured,
)


class ReviewGateClient(GitHubCollabClient):
    def __init__(self, reviews: list[dict[str, object]]) -> None:
        super().__init__(
            app_id="123",
            private_key="key-material",
            allowed_repositories={"arthurkoba/koba-mcp-bridge"},
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


def test_reviewer_config_requires_distinct_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv(
        "GITHUB_REVIEWER_ALLOWED_REPOSITORIES",
        "ArthurKoba/koba-mcp-bridge",
    )
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


def test_reviewer_allowlist_rejects_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REVIEWER_ALLOWED_REPOSITORIES", "*")
    with pytest.raises(GitHubAgentError, match="wildcard"):
        _reviewer_allowed_repositories_from_env()


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
