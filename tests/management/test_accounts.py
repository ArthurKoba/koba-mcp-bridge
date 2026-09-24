from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import select

from management.application.services import AccountService, TelemetryService
from management.domain.accounts import Account, AccountRole, AuthType, Provider
from management.domain.telemetry import Invocation
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import AccountRecord, Base, create_database
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
    database = tmp_path / "control.sqlite3"
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


def test_accounts_are_multi_provider_and_credentials_are_encrypted(tmp_path: Path) -> None:
    engine, sessions, accounts, _telemetry = _services(tmp_path)

    github = accounts.create(
        Account(
            alias="GitHub-Dev",
            provider=Provider.GITHUB,
            role=AccountRole.DEVELOPMENT,
            auth_type=AuthType.GITHUB_APP,
            external_id="12345",
        ),
        credential="github-private-key",
    )
    gitlab = accounts.create(
        Account(
            alias="GitLab-Work",
            provider=Provider.GITLAB,
            role=AccountRole.GENERAL,
            auth_type=AuthType.PRIVATE_TOKEN,
            base_url="https://gitlab.example.test/platform",
        ),
        credential="gitlab-token",
    )

    assert github.alias == "github-dev"
    assert gitlab.alias == "gitlab-work"
    assert gitlab.base_url == "https://gitlab.example.test/platform"

    resolved = accounts.resolve("GITHUB-DEV", provider=Provider.GITHUB)
    assert resolved.id == github.id
    assert resolved.credential == "github-private-key"

    with sessions() as session:
        encrypted = session.scalar(
            select(AccountRecord.encrypted_credential).where(AccountRecord.id == github.id)
        )
    assert encrypted
    assert encrypted != "github-private-key"
    assert "github-private-key" not in str(encrypted)

    public = accounts.list()
    assert {item.alias for item in public} == {"github-dev", "gitlab-work"}
    assert all("credential" not in item.model_dump() for item in public)

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

    accounts.replace_credential(account.id, "new-token")

    assert accounts.resolve(account.id, provider=Provider.GITLAB).credential == "new-token"
    engine.dispose()


def test_invocation_telemetry_is_persisted_without_arguments(tmp_path: Path) -> None:
    engine, _sessions, _accounts, telemetry = _services(tmp_path)
    telemetry.record(
        Invocation(
            request_id="request-1",
            module="github",
            tool="github_agent_status",
            account_id="github-dev",
            provider="github",
            status="success",
            duration_ms=12.5,
        )
    )

    events = telemetry.recent()
    assert len(events) == 1
    assert events[0].tool == "github_agent_status"
    assert events[0].account_id == "github-dev"
    assert not hasattr(events[0], "arguments")
    engine.dispose()


def test_provider_contract_rejects_invalid_role_or_auth() -> None:
    import pytest

    with pytest.raises(ValueError, match="development or reviewer"):
        Account(
            alias="bad-github",
            provider=Provider.GITHUB,
            role=AccountRole.GENERAL,
            auth_type=AuthType.GITHUB_APP,
            external_id="123",
        )

    with pytest.raises(ValueError, match="token based"):
        Account(
            alias="bad-gitlab",
            provider=Provider.GITLAB,
            role=AccountRole.GENERAL,
            auth_type=AuthType.GITHUB_APP,
            base_url="https://gitlab.example.test",
        )
