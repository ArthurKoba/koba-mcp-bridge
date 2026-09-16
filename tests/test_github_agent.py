import base64

import pytest

from koba_mcp_bridge.github_agent import (
    GitHubAgentError,
    GitHubAppClient,
    _allowed_repositories_from_env,
    _private_key_from_env,
    github_agent_configured,
)


def test_github_agent_configured_requires_app_key_and_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "GITHUB_AGENT_APP_ID",
        "GITHUB_AGENT_PRIVATE_KEY",
        "GITHUB_AGENT_PRIVATE_KEY_B64",
        "GITHUB_AGENT_ALLOWED_REPOSITORIES",
    ):
        monkeypatch.delenv(name, raising=False)

    assert github_agent_configured() is False

    monkeypatch.setenv("GITHUB_AGENT_APP_ID", "123")
    monkeypatch.setenv("GITHUB_AGENT_PRIVATE_KEY", "key-material")
    monkeypatch.setenv("GITHUB_AGENT_ALLOWED_REPOSITORIES", "ArthurKoba/koba-mcp-bridge")

    assert github_agent_configured() is True


def test_private_key_can_be_loaded_from_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PRIVATE_KEY", raising=False)
    key_material = "multiline-key-material\nline-two\n"
    monkeypatch.setenv(
        "GITHUB_AGENT_PRIVATE_KEY_B64",
        base64.b64encode(key_material.encode()).decode(),
    )

    assert _private_key_from_env() == key_material


def test_repository_allowlist_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GITHUB_AGENT_ALLOWED_REPOSITORIES",
        "ArthurKoba/koba-mcp-bridge,ArthurKoba/example",
    )
    repos = _allowed_repositories_from_env()
    client = GitHubAppClient(app_id="123", private_key="key", allowed_repositories=repos)

    assert client._assert_allowed("arthurkoba/KOBA-MCP-BRIDGE") == "arthurkoba/KOBA-MCP-BRIDGE"

    with pytest.raises(GitHubAgentError, match="repository is not allowed"):
        client._assert_allowed("someone/else")


def test_repository_allowlist_rejects_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_AGENT_ALLOWED_REPOSITORIES", "*")

    with pytest.raises(GitHubAgentError, match="wildcard"):
        _allowed_repositories_from_env()
