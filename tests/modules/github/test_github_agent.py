import pytest

import modules.github.github_agent as github_agent
from common.settings import GitHubPolicySettings
from modules.github.github_agent import (
    GitHubAgentError,
    GitHubAppClient,
)


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

    client = GitHubAppClient.from_infisical(
        GitHubPolicySettings(
            protected_branches=frozenset({"main", "master"}),
            required_checks=("test", "docker"),
            required_reviewers=(),
        )
    )

    assert client.app_id == "777"
    assert client.private_key == "pem-material"


def test_repository_selector_only_validates_owner_name_shape() -> None:
    client = GitHubAppClient(app_id="123", private_key="key")

    assert client._assert_allowed("ArthurKoba/mcp-bridge") == (
        "ArthurKoba/mcp-bridge"
    )
    assert client._assert_allowed("someone/else") == "someone/else"

    for invalid in ("", "owner", "/repo", "owner/", "owner/repo/extra"):
        with pytest.raises(GitHubAgentError, match="owner/name"):
            client._assert_allowed(invalid)


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
                        "full_name": "ArthurKoba/mcp-bridge",
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
        "ArthurKoba/mcp-bridge",
    ]
    assert client._installation_ids["arthurkoba/ghidra-mcp"] == 99
    assert client._installation_ids["arthurkoba/mcp-bridge"] == 99


def test_app_id_must_be_positive_numeric() -> None:
    client = GitHubAppClient(app_id="not-an-id", private_key="unused")
    with pytest.raises(GitHubAgentError, match="positive numeric"):
        client._app_jwt()


def test_invalid_private_key_reports_actionable_error() -> None:
    client = GitHubAppClient(app_id="123", private_key="not-a-pem")
    with pytest.raises(GitHubAgentError, match=r"PRIVATE_KEY_PEM.*RSA private key"):
        client._app_jwt()


def test_github_401_diagnostics_distinguish_app_and_installation_auth() -> None:
    app_message = GitHubAppClient._github_error_message(
        401,
        "https://api.github.com/app",
        b'{"message":"Bad credentials"}',
    )
    installation_message = GitHubAppClient._github_error_message(
        401,
        "https://api.github.com/repos/owner/repo",
        b'{"message":"Bad credentials"}',
    )

    assert "APP_ID" in app_message
    assert "PRIVATE_KEY_PEM" in app_message
    assert "installation token" in installation_message


def test_github_403_diagnostic_mentions_permissions() -> None:
    message = GitHubAppClient._github_error_message(
        403,
        "https://api.github.com/repos/owner/repo/actions/runs",
        b'{"message":"Resource not accessible by integration"}',
    )
    assert "permissions" in message
    assert "HTTP 403" in message


def test_missing_installation_has_actionable_error() -> None:
    class MissingInstallationClient(GitHubAppClient):
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
            del method, url, token, payload, allowed_errors
            return 404, {"message": "Not Found"}

    client = MissingInstallationClient(app_id="123", private_key="unused")
    with pytest.raises(GitHubAgentError, match=r"not installed.*add it"):
        client._installation_id("owner/repo")


def test_repository_metadata_is_cached_until_refresh() -> None:
    class MetadataClient(GitHubAppClient):
        def __init__(self) -> None:
            super().__init__(
                app_id="123",
                private_key="unused",
                repository_cache_ttl_seconds=60,
            )
            self.calls = 0
            self._installation_ids["owner/repo"] = 7

        def _repo_request(
            self,
            repository: str,
            method: str,
            path: str,
            *,
            payload: object | None = None,
            allowed_errors: set[int] | None = None,
        ) -> tuple[int, object]:
            del repository, method, path, payload, allowed_errors
            self.calls += 1
            return 200, {
                "full_name": "owner/repo",
                "default_branch": "main",
                "private": False,
                "archived": False,
                "fork": False,
            }

    client = MetadataClient()
    first = client.status("owner/repo")
    second = client.status("owner/repo")

    assert first == second
    assert client.calls == 1

    refreshed = client._repository_metadata("owner/repo", refresh=True)
    assert refreshed["repository"] == "owner/repo"
    assert client.calls == 2


def test_infisical_credential_failure_preserves_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_secret(path: str, name: str) -> str:
        del path, name
        raise github_agent.SecretError("Infisical API HTTP 403: denied")

    monkeypatch.setattr(github_agent, "resolve_config_secret", fail_secret)
    with pytest.raises(GitHubAgentError, match="Infisical API HTTP 403"):
        github_agent._development_app_id()

