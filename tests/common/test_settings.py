from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from common.settings import (
    AnalysisSettings,
    BridgeSettings,
    FileSettings,
    GitHubPolicySettings,
    GitLabSettings,
    InfisicalSettings,
)


def test_provider_settings_parse_only_their_own_environment(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", " Main, release ")
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_CHECKS", "test, docker , lint")
    monkeypatch.setenv("GITLAB_PROTECTED_BRANCHES", "main,stable")
    monkeypatch.setenv("GHIDRA_MCP_URL", " http://ghidra:8080/mcp ")
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
    ):
        monkeypatch.delenv(name, raising=False)

    assert BridgeSettings().backends == {
        "github": "http://github:8000/mcp",
        "gitlab": "http://gitlab:8000/mcp",
        "files": "http://files:8000/mcp",
        "http": "http://curl:8000/mcp",
        "analysis": "http://analysis:8000/mcp",
    }


def test_bridge_settings_allow_backend_overrides(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_URL", "http://github-alt:9000/mcp")
    monkeypatch.setenv("GITLAB_URL", "http://gitlab-alt:9000/mcp")
    monkeypatch.setenv("FILES_URL", "http://files-alt:9000/mcp")
    monkeypatch.setenv("CURL_URL", "http://curl-alt:9000/mcp")
    monkeypatch.setenv("ANALYSIS_URL", "http://analysis-alt:9000/mcp")

    assert BridgeSettings().backends == {
        "github": "http://github-alt:9000/mcp",
        "gitlab": "http://gitlab-alt:9000/mcp",
        "files": "http://files-alt:9000/mcp",
        "http": "http://curl-alt:9000/mcp",
        "analysis": "http://analysis-alt:9000/mcp",
    }


def test_infisical_bootstrap_files_are_resolved_at_composition_time(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client_id = tmp_path / "client-id"
    client_secret = tmp_path / "client-secret"
    client_id.write_text("client-id-value\n", encoding="utf-8")
    client_secret.write_text("secret-value\n", encoding="utf-8")

    monkeypatch.setenv("INFISICAL_CLIENT_ID_FILE", str(client_id))
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET_FILE", str(client_secret))
    monkeypatch.setenv("INFISICAL_BASE_PATH", "github")

    config = InfisicalSettings().config()

    assert config.client_id == "client-id-value"
    assert config.client_secret == "secret-value"
    assert config.client_id_source == f"file:{client_id}"
    assert config.client_secret_source == f"file:{client_secret}"
    assert config.base_path == "/github"


def test_infisical_bootstrap_rejects_duplicate_sources(monkeypatch, tmp_path: Path) -> None:
    client_id = tmp_path / "client-id"
    client_id.write_text("file-value", encoding="utf-8")
    monkeypatch.setenv("INFISICAL_CLIENT_ID", "env-value")
    monkeypatch.setenv("INFISICAL_CLIENT_ID_FILE", str(client_id))

    with pytest.raises(ValueError, match="configure only one"):
        InfisicalSettings().config()


def test_file_settings_are_frozen_and_validate_limits() -> None:
    settings = FileSettings(root=Path("/tmp/files"))

    with pytest.raises(ValidationError):
        settings.upload_max_bytes = 1

    with pytest.raises(ValidationError):
        FileSettings(root=Path("relative/path"))
