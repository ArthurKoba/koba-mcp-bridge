from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

pytest.importorskip("starlette_admin")

from common.settings import FileSettings, ManagementSettings
from management.application.services import AccountService, ManagementConfigService, TelemetryService
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import Base, ManagementConfigRecord, create_database
from management.infrastructure.files import FileAdminStore
from management.infrastructure.provider_checks import ProviderConnectionVerifier
from management.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyManagementConfigRepository,
)
from management.presentation.admin import build_admin


def test_starlette_admin_has_provider_logging_and_file_sections(tmp_path: Path) -> None:
    database = tmp_path / "admin.sqlite3"
    engine, sessions = create_database(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with sessions.begin() as session:
        session.add(ManagementConfigRecord(id=1))

    key = Fernet.generate_key().decode()
    settings = ManagementSettings(
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
    telemetry = TelemetryService(SqlAlchemyInvocationRepository(sessions))
    config = ManagementConfigService(SqlAlchemyManagementConfigRepository(sessions))
    files = FileAdminStore(FileSettings(root=tmp_path / "files"))

    admin = build_admin(engine, settings, cipher, accounts, telemetry, config, files)

    assert admin.base_url == "/admin"
    assert admin.index_view.path == "/"
    labels = {view.menu_label for view in admin.views if hasattr(view, "menu_label")}
    assert "GitHub Accounts" in labels
    assert "GitLab Accounts" in labels
    assert "MCP Calls" in labels
    assert "Settings" in labels
    assert "Files" in labels
    engine.dispose()
