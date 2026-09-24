from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import inspect, select

from management.application.services import AccountService, TelemetryService
from management.domain.accounts import Account, AuthType, Provider
from management.domain.telemetry import Invocation
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import (
    Base,
    GitHubAccountRecord,
    GitLabAccountRecord,
    ManagementConfigRecord,
    create_database,
    ensure_zero_state_schema,
)
from management.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyInvocationRepository,
)


class _Verifier:
    def verify(self, account: Account, credential: str) -> dict[str, object]:
        return {
            "ok": True,
            "provider": account.provider.value,
            "alias": account.alias,
            "credential_length": len(credential),
        }


def _services(tmp_path: Path):
    database = tmp_path / "management.sqlite3"
    engine, sessions = create_database(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    cipher = FernetCredentialCipher(Fernet.generate_key().decode())
    account_repository = SqlAlchemyAccountRepository(sessions)
    invocation_repository = SqlAlchemyInvocationRepository(sessions)
    return (
        engine,
        sessions,
        AccountService(account_repository, cipher, _Verifier()),
        TelemetryService(invocation_repository),
    )


def test_accounts_are_provider_specific_and_credentials_are_encrypted(tmp_path: Path) -> None:
    engine, sessions, accounts, _telemetry = _services(tmp_path)

    github = accounts.create(
        Account(
            alias="GitHub-Dev",
            provider=Provider.GITHUB,
            auth_type=AuthType.GITHUB_APP,
            external_id="12345",
        ),
        credential="github-private-key",
    )
    gitlab = accounts.create(
        Account(
            alias="GitLab-Work",
            provider=Provider.GITLAB,
            auth_type=AuthType.PRIVATE_TOKEN,
            base_url="https://gitlab.example.test/platform",
        ),
        credential="gitlab-token",
    )

    assert github.alias == "github-dev"
    assert github.base_url == "https://api.github.com"
    assert gitlab.alias == "gitlab-work"
    assert gitlab.base_url == "https://gitlab.example.test/platform"

    resolved = accounts.resolve("GITHUB-DEV", provider=Provider.GITHUB)
    assert resolved.id == github.id
    assert resolved.credential == "github-private-key"

    with sessions() as session:
        github_secret = session.scalar(
            select(GitHubAccountRecord.encrypted_credential).where(
                GitHubAccountRecord.id == github.id
            )
        )
        gitlab_secret = session.scalar(
            select(GitLabAccountRecord.encrypted_credential).where(
                GitLabAccountRecord.id == gitlab.id
            )
        )
    assert github_secret and github_secret != "github-private-key"
    assert gitlab_secret and gitlab_secret != "gitlab-token"

    public = accounts.list()
    assert {item.alias for item in public} == {"github-dev", "gitlab-work"}
    assert all("credential" not in item.model_dump() for item in public)
    engine.dispose()


def test_account_discovery_includes_disabled_but_resolve_rejects_them(tmp_path: Path) -> None:
    engine, _sessions, accounts, _telemetry = _services(tmp_path)
    disabled = accounts.create(
        Account(
            alias="github-disabled",
            provider=Provider.GITHUB,
            auth_type=AuthType.GITHUB_TOKEN,
            enabled=False,
        ),
        credential="github-token",
    )

    listed = accounts.list(provider=Provider.GITHUB)
    assert [item.id for item in listed] == [disabled.id]
    assert listed[0].enabled is False

    with pytest.raises(KeyError, match="GitHub account not found"):
        accounts.resolve(disabled.id, provider=Provider.GITHUB)
    engine.dispose()


def test_github_token_account_does_not_require_app_id(tmp_path: Path) -> None:
    engine, _sessions, accounts, _telemetry = _services(tmp_path)
    account = accounts.create(
        Account(
            alias="github-user",
            provider=Provider.GITHUB,
            auth_type=AuthType.GITHUB_TOKEN,
        ),
        credential="github-token",
    )
    assert account.external_id == ""
    assert accounts.resolve(account.id, provider=Provider.GITHUB).credential == "github-token"
    engine.dispose()


def test_replace_credential_invalidates_old_value(tmp_path: Path) -> None:
    engine, _sessions, accounts, _telemetry = _services(tmp_path)
    account = accounts.create(
        Account(
            alias="gitlab-local",
            provider=Provider.GITLAB,
            auth_type=AuthType.BEARER,
            base_url="http://gitlab.local",
        ),
        credential="old-token",
    )

    accounts.set_credential(account.id, "new-token", provider=Provider.GITLAB)

    assert accounts.resolve(account.id, provider=Provider.GITLAB).credential == "new-token"
    engine.dispose()


def test_invocation_telemetry_captures_payloads_and_can_be_disabled(tmp_path: Path) -> None:
    engine, sessions, _accounts, telemetry = _services(tmp_path)
    telemetry.record(
        Invocation(
            request_id="request-1",
            module="github",
            tool="github_status",
            account_id="github-dev",
            provider="github",
            status="success",
            duration_ms=12.5,
            arguments_json='{"repository":"ArthurKoba/mcp-bridge"}',
            result_json='{"ok":true}',
        )
    )
    events = telemetry.recent()
    assert len(events) == 1
    assert events[0].arguments_json.startswith("{")
    assert events[0].result_json.startswith("{")

    with sessions.begin() as session:
        config = session.get(ManagementConfigRecord, 1)
        assert config is not None
        config.logging_enabled = False

    telemetry.record(
        Invocation(
            module="gitlab",
            tool="gitlab_projects",
            status="success",
            duration_ms=1,
        )
    )
    assert len(telemetry.recent()) == 1
    engine.dispose()


def test_provider_contracts_are_separate() -> None:
    with pytest.raises(ValueError, match="GitHub auth_type"):
        Account(
            alias="bad-github",
            provider=Provider.GITHUB,
            auth_type=AuthType.PRIVATE_TOKEN,
        )

    with pytest.raises(ValueError, match="token based"):
        Account(
            alias="bad-gitlab",
            provider=Provider.GITLAB,
            auth_type=AuthType.GITHUB_APP,
            base_url="https://gitlab.example.test",
        )

    with pytest.raises(ValueError, match="APP_ID"):
        Account(
            alias="bad-app",
            provider=Provider.GITHUB,
            auth_type=AuthType.GITHUB_APP,
        )


def test_zero_state_schema_resets_incompatible_management_database(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    engine, _sessions = create_database(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE github_accounts (id TEXT PRIMARY KEY, label TEXT NOT NULL)"
        )

    assert ensure_zero_state_schema(engine) is True

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("github_accounts")}
    assert "label" not in columns
    assert columns == {column.name for column in GitHubAccountRecord.__table__.columns}
    assert ensure_zero_state_schema(engine) is False
    engine.dispose()
