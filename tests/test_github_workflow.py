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



def test_required_checks_delegate_when_names_do_not_belong_to_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_CHECKS", "test,docker")
    dev = client()

    def fake_check_runs(repository: str, ref: str) -> dict[str, object]:
        return {
            "repository": repository,
            "ref": ref,
            "check_runs": [
                {
                    "name": "Build Status",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        **kwargs: object,
    ) -> tuple[int, object]:
        assert method == "GET"
        assert endpoint == f"/repos/{repository}"
        return 200, {"default_branch": "main"}

    monkeypatch.setattr(dev, "check_runs", fake_check_runs)
    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    result = dev.assert_required_checks("ArthurKoba/ghidra-mcp", "head-sha")

    assert result["status"] == "delegated_to_github"


def test_required_checks_stay_strict_when_repository_uses_configured_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_CHECKS", "test,docker")
    dev = client()

    def fake_check_runs(repository: str, ref: str) -> dict[str, object]:
        if ref == "head-sha":
            checks = [
                {"name": "test", "status": "completed", "conclusion": "success"},
            ]
        else:
            checks = [
                {"name": "test", "status": "completed", "conclusion": "success"},
                {"name": "docker", "status": "completed", "conclusion": "success"},
            ]
        return {"repository": repository, "ref": ref, "check_runs": checks}

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        **kwargs: object,
    ) -> tuple[int, object]:
        return 200, {"default_branch": "main"}

    monkeypatch.setattr(dev, "check_runs", fake_check_runs)
    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    with pytest.raises(GitHubAgentError, match="missing=\\['docker'\\]"):
        dev.assert_required_checks("ArthurKoba/koba-mcp-bridge", "head-sha")
