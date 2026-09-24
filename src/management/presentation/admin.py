from __future__ import annotations

import asyncio
import hmac
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.base import Executable
from starlette.requests import Request
from starlette_admin import (
    CardRowWidget,
    CustomView,
    EnumField,
    PasswordField,
    StatWidget,
    TextAreaField,
    flash,
)
from starlette_admin.actions import row_action
from starlette_admin.auth import AdminUser, AuthProvider, LoginFailed
from starlette_admin.contrib.sqla import Admin, ModelView
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import BaseField

from common.settings import ManagementSettings
from management.application.services import AccountService
from management.domain.accounts import Account, AccountRole, AuthType, Provider
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import AccountRecord, InvocationRecord


class ManagementAuthProvider(AuthProvider):
    def __init__(self, settings: ManagementSettings) -> None:
        super().__init__()
        self.settings = settings

    async def login(
        self,
        username: str,
        password: str,
        remember_me: bool,
        request: Request,
    ) -> None:
        del remember_me
        valid_user = hmac.compare_digest(username, self.settings.admin_username)
        valid_password = hmac.compare_digest(password, self.settings.admin_password)
        if not (valid_user and valid_password):
            raise LoginFailed("Invalid username or password")
        request.session["management_admin"] = self.settings.admin_username

    async def authenticate(self, request: Request) -> AdminUser | None:
        username = request.session.get("management_admin")
        if not isinstance(username, str) or not username:
            return None
        return AdminUser(username=username)

    async def logout(self, request: Request) -> None:
        request.session.clear()


class AccountView(ModelView):
    fields = cast(Sequence[BaseField], (
        "id",
        "alias",
        EnumField(
            "provider",
            choices=[(item.value, item.value.title()) for item in Provider],
            required=True,
        ),
        EnumField(
            "role",
            choices=[(item.value, item.value.title()) for item in AccountRole],
            required=True,
        ),
        EnumField(
            "auth_type",
            choices=[(item.value, item.value.replace("_", " ").title()) for item in AuthType],
            required=True,
        ),
        "label",
        "base_url",
        "external_id",
        "verify_tls",
        TextAreaField("ca_cert_pem", label="Custom CA certificate PEM"),
        "enabled",
        PasswordField(
            "credential_input",
            label="Credential / private key",
            required=False,
            exclude_from_list=True,
            exclude_from_detail=True,
            getter=lambda _request, _obj: "",
            help_text=(
                "GitHub App: private key PEM. GitLab: access token. "
                "Leave blank on edit to keep the stored credential."
            ),
        ),
        "created_at",
        "updated_at",
    ))
    searchable_fields = ("alias", "label", "base_url", "external_id")
    exclude_fields_from_create = ("id", "created_at", "updated_at")
    exclude_fields_from_edit = ("id", "created_at", "updated_at")
    row_actions = ("view", "edit", "test_connection", "delete")

    def __init__(
        self,
        model: type[AccountRecord],
        cipher: FernetCredentialCipher,
        accounts: AccountService,
    ) -> None:
        super().__init__(model, icon="fa fa-key")
        self.cipher = cipher
        self.accounts = accounts

    @staticmethod
    def _validated(obj: AccountRecord) -> Account:
        return Account(
            id=obj.id,
            alias=obj.alias,
            provider=Provider(obj.provider),
            role=AccountRole(obj.role),
            auth_type=AuthType(obj.auth_type),
            label=obj.label,
            base_url=obj.base_url,
            external_id=obj.external_id,
            verify_tls=obj.verify_tls,
            ca_cert_pem=obj.ca_cert_pem,
            enabled=obj.enabled,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )

    @staticmethod
    def _apply_normalized(obj: AccountRecord, account: Account) -> None:
        obj.alias = account.alias
        obj.provider = account.provider.value
        obj.role = account.role.value
        obj.auth_type = account.auth_type.value
        obj.label = account.label
        obj.base_url = account.base_url
        obj.external_id = account.external_id
        obj.verify_tls = account.verify_tls
        obj.ca_cert_pem = account.ca_cert_pem
        obj.enabled = account.enabled

    async def before_create(
        self,
        request: Request,
        data: dict[str, object],
        obj: AccountRecord,
    ) -> None:
        del request, data
        secret = obj._credential_input.strip()
        if not secret:
            raise ValueError("credential is required when creating an account")
        now = datetime.now(UTC)
        if not obj.id:
            obj.id = str(uuid4())
        obj.created_at = now
        obj.updated_at = now
        account = self._validated(obj)
        self._apply_normalized(obj, account)
        obj.encrypted_credential = self.cipher.encrypt(secret)
        obj._credential_input = ""

    async def before_edit(
        self,
        request: Request,
        data: dict[str, object],
        obj: AccountRecord,
    ) -> None:
        del request, data
        obj.updated_at = datetime.now(UTC)
        account = self._validated(obj)
        self._apply_normalized(obj, account)
        secret = obj._credential_input.strip()
        if secret:
            obj.encrypted_credential = self.cipher.encrypt(secret)
        obj._credential_input = ""

    @row_action(
        name="test_connection",
        text="Test connection",
        icon_class="fa fa-plug",
    )
    async def test_connection(self, request: Request, pk: object) -> None:
        try:
            result = self.accounts.verify(str(pk))
        except Exception as exc:
            raise ActionFailed(str(exc)) from exc
        provider = str(result.get("provider", "provider"))
        flash(request, f"{provider} connection verified successfully", "success")


class InvocationView(ModelView):
    fields = cast(Sequence[BaseField], (
        "id",
        "occurred_at",
        "module",
        "tool",
        "provider",
        "account_id",
        "status",
        "duration_ms",
        "error_type",
        "request_id",
    ))
    searchable_fields = ("module", "tool", "provider", "account_id", "error_type")

    def can_create(self, _request: Request) -> bool:
        return False

    def can_edit(self, _request: Request) -> bool:
        return False

    def can_delete(self, _request: Request) -> bool:
        return True


def _dashboard(engine: Engine) -> CustomView:
    async def count_accounts(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.count()).select_from(AccountRecord).where(AccountRecord.enabled.is_(True)),
        )

    async def count_github(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.count())
            .select_from(AccountRecord)
            .where(
                AccountRecord.provider == Provider.GITHUB.value,
                AccountRecord.enabled.is_(True),
            ),
        )

    async def count_gitlab(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.count())
            .select_from(AccountRecord)
            .where(
                AccountRecord.provider == Provider.GITLAB.value,
                AccountRecord.enabled.is_(True),
            ),
        )

    async def count_calls(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.count()).select_from(InvocationRecord),
        )

    async def count_errors(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.count())
            .select_from(InvocationRecord)
            .where(InvocationRecord.status == "error"),
        )

    async def average_duration(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.avg(InvocationRecord.duration_ms)),
        )

    return CustomView(
        menu_label="Dashboard",
        icon="fa fa-home",
        path="/dashboard",
        widget=CardRowWidget(
            children=[
                StatWidget(title="Active accounts", value_callback=count_accounts),
                StatWidget(title="GitHub accounts", value_callback=count_github),
                StatWidget(title="GitLab accounts", value_callback=count_gitlab),
                StatWidget(title="MCP calls", value_callback=count_calls),
                StatWidget(title="Errors", value_callback=count_errors),
                StatWidget(title="Average duration (ms)", value_callback=average_duration),
            ]
        ),
    )


def _scalar(engine: Engine, statement: Executable) -> int:
    with engine.connect() as connection:
        value = connection.scalar(statement)
    if value is None:
        return 0
    return round(float(value))


def build_admin(
    engine: Engine,
    settings: ManagementSettings,
    cipher: FernetCredentialCipher,
    accounts: AccountService,
) -> Admin:
    admin = Admin(
        engine,
        title="MCP Management",
        base_url="/admin",
        auth_provider=ManagementAuthProvider(settings),
        secret_key=settings.session_secret,
        index_view=_dashboard(engine),
    )
    admin.add_view(AccountView(AccountRecord, cipher, accounts))
    admin.add_view(InvocationView(InvocationRecord, icon="fa fa-chart-line"))
    return admin
