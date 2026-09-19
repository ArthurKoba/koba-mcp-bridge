import base64

import pytest

import koba_mcp_bridge.github_agent as github_agent
from koba_mcp_bridge.github_agent import (
    GitHubAgentError,
    GitHubAppClient,
    _private_key_from_env,
    github_agent_configured,
)


def test_github_agent_configured_requires_only_app_id_and_key(
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

    assert github_agent_configured() is True


def test_github_agent_loads_convention_config_from_infisical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_agent,
        "resolve_config_secret",
        lambda path, name: {
            ("github/development", "APP_ID"): "777",
            ("github/development", "PRIVATE_KEY_PEM"): "pem-material",
        }[(path, name)],
    )

    client = GitHubAppClient.from_env()

    assert client.app_id == "777"
    assert client.private_key == "pem-material"


def test_private_key_can_be_loaded_from_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PRIVATE_KEY", raising=False)
    key_material = "multiline-key-material\nline-two\n"
    monkeypatch.setenv(
        "GITHUB_AGENT_PRIVATE_KEY_B64",
        base64.b64encode(key_material.encode()).decode(),
    )

    assert _private_key_from_env() == key_material


def test_repository_selector_only_validates_owner_name_shape() -> None:
    client = GitHubAppClient(app_id="123", private_key="key")

    assert client._assert_allowed("ArthurKoba/koba-mcp-bridge") == (
        "ArthurKoba/koba-mcp-bridge"
    )
    assert client._assert_allowed("someone/else") == "someone/else"

    for invalid in ("", "owner", "/repo", "owner/", "owner/repo/extra"):
        with pytest.raises(GitHubAgentError, match="owner/name"):
            client._assert_allowed(invalid)


def test_request_reuses_persistent_github_https_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = []
    targets = []

    class FakeResponse:
        status = 200
        will_close = False

        def read(self) -> bytes:
            return b'{"ok":true}'

    class FakeConnection:
        def __init__(self, host, *, timeout, context):
            assert host == "api.github.com"
            assert timeout == 30
            assert context is not None
            created.append(self)

        def request(self, method, target, *, body=None, headers=None):
            assert method == "GET"
            assert body is None
            assert headers["User-Agent"] == "koba-mcp-bridge"
            targets.append(target)

        def getresponse(self):
            return FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr(
        github_agent.http.client,
        "HTTPSConnection",
        FakeConnection,
    )

    client = GitHubAppClient(app_id="123", private_key="key")
    first = client._request(
        "GET",
        "https://api.github.com/repos/ArthurKoba/koba-mcp-bridge?probe=1",
    )
    second = client._request(
        "GET",
        "https://api.github.com/repos/ArthurKoba/koba-mcp-bridge?probe=2",
    )

    assert first == (200, {"ok": True})
    assert second == (200, {"ok": True})
    assert len(created) == 1
    assert targets == [
        "/repos/ArthurKoba/koba-mcp-bridge?probe=1",
        "/repos/ArthurKoba/koba-mcp-bridge?probe=2",
    ]


class RecordingInstallationClient(GitHubAppClient):
    def _app_jwt(self) -> str:
        return "app-jwt"

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del payload, allowed_errors
        if method == "GET" and url.endswith("/app/installations?per_page=100&page=1"):
            assert token == "app-jwt"
            return 200, [{"id": 99}]
        if method == "POST" and url.endswith("/app/installations/99/access_tokens"):
            assert token == "app-jwt"
            return 201, {
                "token": "installation-token",
                "expires_at": "2099-01-01T00:00:00Z",
            }
        if method == "GET" and url.endswith("/installation/repositories?per_page=100&page=1"):
            assert token == "installation-token"
            return 200, {
                "total_count": 2,
                "repositories": [
                    {
                        "full_name": "ArthurKoba/koba-mcp-bridge",
                        "private": False,
                        "default_branch": "main",
                        "archived": False,
                        "fork": False,
                        "permissions": {"push": True, "pull": True},
                    },
                    {
                        "full_name": "ArthurKoba/ghidra-mcp",
                        "private": False,
                        "default_branch": "main",
                        "archived": False,
                        "fork": False,
                        "permissions": {"push": True, "pull": True},
                    },
                ],
            }
        raise AssertionError(f"unexpected request: {method} {url}")


def test_list_repositories_uses_github_installation_scope() -> None:
    client = RecordingInstallationClient(app_id="123", private_key="key")
    result = client.list_repositories()

    assert result["app_id"] == "123"
    assert result["count"] == 2
    assert [repo["full_name"] for repo in result["repositories"]] == [
        "ArthurKoba/ghidra-mcp",
        "ArthurKoba/koba-mcp-bridge",
    ]
    assert client._installation_ids["arthurkoba/ghidra-mcp"] == 99
    assert client._installation_ids["arthurkoba/koba-mcp-bridge"] == 99
