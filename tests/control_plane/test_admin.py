from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

pytest.importorskip("starlette_admin")

from common.settings import ControlPlaneSettings
from control_plane.application.services import AccountService
from control_plane.infrastructure.crypto import FernetCredentialCipher
from control_plane.infrastructure.database import Base, create_database
from control_plane.infrastructure.provider_checks import ProviderConnectionVerifier
from control_plane.infrastructure.repositories import SqlAlchemyAccountRepository
from control_plane.presentation.admin import build_admin


def test_starlette_admin_mount_contract(tmp_path: Path) -> None:
    database = tmp_path / "admin.sqlite3"
    engine, sessions = create_database(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    key = Fernet.generate_key().decode()
    settings = ControlPlaneSettings(
        database_path=database,
        encryption_key=key,
        service_token="service-token",
        admin_username="admin",
        admin_password="password",
        session_secret="session-secret",
        session_https_only=False,
    )
    cipher = FernetCredentialCipher(key)
    accounts = AccountService(
        SqlAlchemyAccountRepository(sessions),
        cipher,
        ProviderConnectionVerifier(),
    )

    admin = build_admin(engine, settings, cipher, accounts)

    assert admin.base_url == "/admin"
    engine.dispose()
