from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from common.settings import ControlPlaneSettings
from control_plane.application.services import AccountService, TelemetryService
from control_plane.infrastructure.crypto import FernetCredentialCipher
from control_plane.infrastructure.database import create_database
from control_plane.infrastructure.migrations import run_migrations
from control_plane.infrastructure.provider_checks import ProviderConnectionVerifier
from control_plane.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyInvocationRepository,
)
from control_plane.presentation.admin import build_admin
from control_plane.presentation.api import ApiServices, build_internal_router

settings = ControlPlaneSettings()
settings.validate_bootstrap()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)

run_migrations(settings.database_url)
engine, sessions = create_database(settings.database_url)

cipher = FernetCredentialCipher(settings.encryption_key)
account_repository = SqlAlchemyAccountRepository(sessions)
invocation_repository = SqlAlchemyInvocationRepository(sessions)
accounts = AccountService(account_repository, cipher, ProviderConnectionVerifier())
telemetry = TelemetryService(invocation_repository)

app = FastAPI(
    title="MCP Control Plane",
    docs_url=None,
    redoc_url=None,
    middleware=[
        Middleware(
            SessionMiddleware,
            secret_key=settings.session_secret,
            https_only=settings.session_https_only,
            same_site="lax",
        )
    ],
)
app.include_router(
    build_internal_router(
        ApiServices(
            accounts=accounts,
            telemetry=telemetry,
            service_token=settings.service_token,
        )
    )
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


admin = build_admin(engine, settings, cipher, accounts)
admin.mount_to(app)
