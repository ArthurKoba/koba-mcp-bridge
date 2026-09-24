from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from common.settings import (
    AnalysisSettings,
    BridgeSettings,
    ControlPlaneClientSettings,
    ControlPlaneSettings,
    FileSettings,
    GitHubPolicySettings,
    GitLabSettings,
)


def test_provider_settings_parse_only_their_own_environment(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", " Main, release ")
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_CHECKS", "test, docker , lint")
    monkeypatch.setenv("GITLAB_PROTECTED_BRANCHES", "main,stable")
    monkeypatch.setenv("GHIDRA_URL", " http://ghidra:8080/mcp ")
    monkeypatch.setenv("ANALYSIS_SCHEMA_CACHE_TTL_SECONDS", "45")
    monkeypatch.setenv("FILE_ROOT", "/tmp/mcp-files")
    monkeypatch.setenv("FILE_UPLOAD_CHUNK_BYTES", str(256 * 1024))

    github = GitHubPolicySettings()
    gitlab = GitLabSettings()
    analysis = AnalysisSettings()
    files = FileSettings()

    assert github.protected_branches == {"main", "release"}
    assert github.required_checks == ("test", "docker", "lint")
    assert gitlab.protected_branches == {"main", "stable"}
    assert analysis.backend_url == "http://ghidra:8080/mcp"
    assert analysis.schema_cache_ttl_seconds == 45
    assert files.root == Path("/tmp/mcp-files")
    assert files.upload_chunk_bytes == 256 * 1024


def test_unrelated_invalid_environment_does_not_break_file_settings(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_REGISTRY_CACHE_TTL_SECONDS", "not-a-number")
    monkeypatch.setenv("FILE_ROOT", "/tmp/mcp-files")

    assert FileSettings().root == Path("/tmp/mcp-files")
    with pytest.raises(ValidationError):
        GitLabSettings()


def test_bridge_settings_use_canonical_backends_by_default(monkeypatch) -> None:
    for name in (
        "GITHUB_URL",
        "GITLAB_URL",
        "FILES_URL",
        "CURL_URL",
        "ANALYSIS_URL",
        "GHIDRA_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert BridgeSettings().backends == {
        "github": "http://github:8000/mcp",
        "gitlab": "http://gitlab:8000/mcp",
        "files": "http://files:8000/mcp",
        "web": "http://curl:8000/mcp",
        "analysis": "http://analysis:8000/mcp",
        "ghidra": "http://ghidra:8000/mcp",
    }


def test_gateway_oauth_bootstrap_is_typed(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", " client ")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", " secret ")
    monkeypatch.setenv("GITHUB_OAUTH_JWT_SIGNING_KEY", " jwt ")
    monkeypatch.setenv("GITHUB_OAUTH_ALLOWED_USERS", "ArthurKoba, ReviewerBot")

    settings = BridgeSettings()

    assert settings.oauth_client_id == "client"
    assert settings.oauth_client_secret == "secret"
    assert settings.oauth_jwt_signing_key == "jwt"
    assert settings.oauth_allowed_users == ("arthurkoba", "reviewerbot")


def test_control_plane_client_settings_allow_import_without_bootstrap(monkeypatch) -> None:
    monkeypatch.delenv("CONTROL_PLANE_SERVICE_TOKEN", raising=False)
    settings = ControlPlaneClientSettings()
    assert settings.url == "http://control-plane:8000"
    assert settings.service_token == ""


def test_control_plane_settings_validate_bootstrap(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "control.sqlite3"
    monkeypatch.setenv("CONTROL_PLANE_DATABASE_PATH", str(db))
    monkeypatch.setenv("CONTROL_PLANE_ENCRYPTION_KEY", "key")
    monkeypatch.setenv("CONTROL_PLANE_SERVICE_TOKEN", "service")
    monkeypatch.setenv("CONTROL_PLANE_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("CONTROL_PLANE_SESSION_SECRET", "session")

    settings = ControlPlaneSettings()
    settings.validate_bootstrap()

    assert settings.database_path == db
    assert settings.database_url == f"sqlite:///{db}"


def test_control_plane_settings_reject_missing_bootstrap(monkeypatch) -> None:
    for name in (
        "CONTROL_PLANE_ENCRYPTION_KEY",
        "CONTROL_PLANE_SERVICE_TOKEN",
        "CONTROL_PLANE_ADMIN_PASSWORD",
        "CONTROL_PLANE_SESSION_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="missing control-plane bootstrap settings"):
        ControlPlaneSettings().validate_bootstrap()


def test_file_settings_are_frozen_and_validate_limits() -> None:
    settings = FileSettings(root=Path("/tmp/files"))

    with pytest.raises(ValidationError):
        settings.upload_max_bytes = 1

    with pytest.raises(ValidationError):
        FileSettings(root=Path("relative/path"))
