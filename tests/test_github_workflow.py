import pytest

from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_workflow import (
    GitHubDevClient,
    protected_branches_from_env,
    required_checks_from_env,
)


def client() -> GitHubDevClient:
    return GitHubDevClient(
        app_id="123",
        private_key="key-material",
        allowed_repositories={"arthurkoba/koba-mcp-bridge"},
    )


def test_default_protected_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    assert protected_branches_from_env() == {"main", "master"}


def test_custom_protected_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "main,release")
    assert protected_branches_from_env() == {"main", "release"}


def test_default_required_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_REQUIRED_CHECKS", raising=False)
    assert required_checks_from_env() == ["test", "docker"]


def test_direct_write_to_main_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    with pytest.raises(GitHubAgentError, match="protected branch"):
        client().put_file(
            "ArthurKoba/koba-mcp-bridge",
            "README.md",
            "content",
            "message",
            "main",
        )


def test_fast_forward_main_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    with pytest.raises(GitHubAgentError, match="protected branch"):
        client().fast_forward("ArthurKoba/koba-mcp-bridge", "main", "feature")


def test_cross_repository_pull_request_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="cross-repository"):
        client().create_pull_request(
            "ArthurKoba/koba-mcp-bridge",
            "title",
            "someone:branch",
            "main",
        )


def test_same_head_and_base_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="head and base"):
        client().create_pull_request(
            "ArthurKoba/koba-mcp-bridge",
            "title",
            "main",
            "main",
        )


def test_empty_atomic_commit_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="changes must not be empty"):
        client().commit_files(
            "ArthurKoba/koba-mcp-bridge",
            "feature/test",
            "message",
            [],
        )


def test_invalid_binary_content_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="valid base64"):
        client().put_binary_file(
            "ArthurKoba/koba-mcp-bridge",
            "payload.bin",
            "not base64!",
            "message",
            "feature/test",
        )


def test_invalid_review_event_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="event must be"):
        client().create_review(
            "ArthurKoba/koba-mcp-bridge",
            1,
            "SHIP_IT",
            "body",
        )


def test_invalid_merge_method_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="merge_method"):
        client().merge_pull_request(
            "ArthurKoba/koba-mcp-bridge",
            1,
            "octopus",
        )
