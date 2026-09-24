from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from common.settings import FileSettings, ManagementSettings
from management.application.services import AccountService, ManagementConfigService, TelemetryService
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import create_database, ensure_zero_state_schema
from management.infrastructure.files import FileAdminStore
from management.infrastructure.provider_checks import ProviderConnectionVerifier
from management.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyManagementConfigRepository,
)
from management.presentation.admin import build_admin
from management.presentation.api import ApiServices, build_internal_router

logger = logging.getLogger(__name__)

settings = ManagementSettings()
settings.validate_bootstrap()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine, sessions = create_database(settings.database_url)
if ensure_zero_state_schema(engine):
    logger.warning("management schema changed; reset zero-state management database")

cipher = FernetCredentialCipher(settings.encryption_key)
account_repository = SqlAlchemyAccountRepository(sessions)
invocation_repository = SqlAlchemyInvocationRepository(sessions)
config_repository = SqlAlchemyManagementConfigRepository(sessions)
config_service = ManagementConfigService(config_repository)
config_service.get()
accounts = AccountService(account_repository, cipher, ProviderConnectionVerifier())
telemetry = TelemetryService(invocation_repository)
files = FileAdminStore(FileSettings())


async def _maintenance_loop() -> None:
    interval_seconds = 3600
    while True:
        try:
            config = await asyncio.to_thread(config_service.get)
            interval_seconds = config.maintenance_interval_minutes * 60
            await asyncio.to_thread(telemetry.cleanup)
            if config.file_auto_cleanup_enabled:
                await asyncio.to_thread(
                    files.cleanup,
                    retention_days=config.file_retention_days,
                    limit=config.file_cleanup_limit,
                    dry_run=False,
                )
        except Exception:
            logger.exception("management maintenance cycle failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_maintenance_loop(), name="management-maintenance")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(
    title="MCP Management",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
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


admin = build_admin(engine, settings, cipher, accounts, telemetry, config_service, files)
admin.mount_to(app)
