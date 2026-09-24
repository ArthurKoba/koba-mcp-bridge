from __future__ import annotations

import asyncio
import hmac
import urllib.parse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.base import Executable
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette_admin import (
    Breakpoints,
    CardRowWidget,
    Col,
    CustomView,
    EnumField,
    PasswordField,
    RowActionsDisplayType,
    StatWidget,
    TextAreaField,
    action,
    flash,
    route,
)
from starlette_admin.actions import row_action
from starlette_admin.auth import AdminUser, AuthProvider, LoginFailed
from starlette_admin.contrib.sqla import Admin, ModelView
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import BaseField
from starlette_admin.theme import ClassMap, DefaultTheme

from common.settings import ManagementSettings
from management.application.services import AccountService, TelemetryService
from management.domain.accounts import Account, AuthType, Provider
from management.domain.configuration import ManagementConfig
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import (
    GitHubAccountRecord,
    GitLabAccountRecord,
    InvocationRecord,
    ManagementConfigRecord,
)
from management.infrastructure.files import FileAdminStore


class _CompactClasses(ClassMap):
    classes = {
        "list.search_button": "btn btn-sm",
        "list.create_button": "btn btn-sm btn-primary ms-1",
        "list.import_button": "btn btn-sm",
        "list.columns_toggle": "btn btn-sm dropdown-toggle",
        "list.goto_page_button": "btn btn-sm",
        "filter.toggle_button": "btn btn-sm dropdown-toggle",
        "action.button": "btn btn-sm",
        "action.dropdown_toggle": "btn btn-sm dropdown-toggle",
    }


class _CompactTheme(DefaultTheme):
    def get_class_map(self) -> ClassMap:
        return _CompactClasses()


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


class _BaseAccountView(ModelView):
    row_actions = ("view", "edit", "test_connection", "delete")
    row_actions_display_type = RowActionsDisplayType.KEBAB
    page_size = 25
    page_size_options = [25, 50, 100]
    search_auto_submit = True
    exclude_fields_from_create = ("id", "encrypted_credential", "created_at", "updated_at")
    exclude_fields_from_edit = ("id", "encrypted_credential", "created_at", "updated_at")

    provider: Provider

    def __init__(
        self,
        model: type[GitHubAccountRecord] | type[GitLabAccountRecord],
        cipher: FernetCredentialCipher,
        accounts: AccountService,
        *,
        icon: str,
        label: str,
    ) -> None:
        super().__init__(model, icon=icon, menu_label=label, display_name=label.rstrip("s"))
        self.cipher = cipher
        self.accounts = accounts

    def _validated(self, obj: GitHubAccountRecord | GitLabAccountRecord) -> Account:
        if self.provider is Provider.GITHUB:
            record = cast(GitHubAccountRecord, obj)
            return Account(
                id=record.id,
                alias=record.alias,
                provider=Provider.GITHUB,
                auth_type=AuthType(record.auth_type),
                label=record.label,
                external_id=record.app_id,
                enabled=record.enabled,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        record = cast(GitLabAccountRecord, obj)
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.GITLAB,
            auth_type=AuthType(record.auth_type),
            label=record.label,
            base_url=record.base_url,
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _apply_normalized(
        self,
        obj: GitHubAccountRecord | GitLabAccountRecord,
        account: Account,
    ) -> None:
        obj.alias = account.alias
        obj.auth_type = account.auth_type.value
        obj.label = account.label
        obj.enabled = account.enabled
        if self.provider is Provider.GITHUB:
            cast(GitHubAccountRecord, obj).app_id = account.external_id
            return
        record = cast(GitLabAccountRecord, obj)
        record.base_url = account.base_url
        record.verify_tls = account.verify_tls
        record.ca_cert_pem = account.ca_cert_pem

    async def before_create(
        self,
        request: Request,
        data: dict[str, object],
        obj: GitHubAccountRecord | GitLabAccountRecord,
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
        obj: GitHubAccountRecord | GitLabAccountRecord,
    ) -> None:
        del request, data
        obj.updated_at = datetime.now(UTC)
        account = self._validated(obj)
        self._apply_normalized(obj, account)
        secret = obj._credential_input.strip()
        if secret:
            obj.encrypted_credential = self.cipher.encrypt(secret)
        obj._credential_input = ""

    @row_action(name="test_connection", text="Test connection", icon_class="fa fa-plug")
    async def test_connection(self, request: Request, pk: object) -> None:
        try:
            result = self.accounts.verify(str(pk), provider=self.provider)
        except Exception as exc:
            raise ActionFailed(str(exc)) from exc
        provider = str(result.get("provider", self.provider.value))
        flash(request, f"{provider} connection verified successfully", "success")


class GitHubAccountView(_BaseAccountView):
    provider = Provider.GITHUB
    fields = cast(
        Sequence[BaseField],
        (
            "id",
            "alias",
            EnumField(
                "auth_type",
                choices=[
                    (AuthType.GITHUB_APP.value, "GitHub App"),
                    (AuthType.GITHUB_TOKEN.value, "Personal / user token"),
                ],
                required=True,
            ),
            "label",
            "app_id",
            "enabled",
            PasswordField(
                "credential_input",
                label="Token / private key",
                required=False,
                exclude_from_list=True,
                exclude_from_detail=True,
                getter=lambda _request, _obj: "",
                help_text=(
                    "GitHub App: private key PEM and App ID. Token account: PAT/user token; "
                    "App ID is ignored. Leave blank on edit to keep the stored credential."
                ),
            ),
            "created_at",
            "updated_at",
        ),
    )
    searchable_fields = ("alias", "label", "app_id")


class GitLabAccountView(_BaseAccountView):
    provider = Provider.GITLAB
    fields = cast(
        Sequence[BaseField],
        (
            "id",
            "alias",
            "label",
            "base_url",
            EnumField(
                "auth_type",
                choices=[
                    (AuthType.PRIVATE_TOKEN.value, "Private token"),
                    (AuthType.BEARER.value, "OAuth / bearer token"),
                    (AuthType.JOB_TOKEN.value, "Job token"),
                ],
                required=True,
            ),
            "verify_tls",
            TextAreaField("ca_cert_pem", label="Custom CA certificate PEM"),
            "enabled",
            PasswordField(
                "credential_input",
                label="Access token",
                required=False,
                exclude_from_list=True,
                exclude_from_detail=True,
                getter=lambda _request, _obj: "",
                help_text="Leave blank on edit to keep the stored token.",
            ),
            "created_at",
            "updated_at",
        ),
    )
    searchable_fields = ("alias", "label", "base_url")


class InvocationView(ModelView):
    row_actions_display_type = RowActionsDisplayType.KEBAB
    page_size = 50
    page_size_options = [25, 50, 100]
    fields = cast(
        Sequence[BaseField],
        (
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
            TextAreaField("arguments_json", label="Arguments"),
            TextAreaField("result_json", label="Result"),
            TextAreaField("error_message", label="Error message"),
        ),
    )
    searchable_fields = ("module", "tool", "provider", "account_id", "error_type", "request_id")
    exclude_fields_from_list = ("arguments_json", "result_json", "error_message")
    actions = ("clear_all", "delete")

    def __init__(self, model: type[InvocationRecord], telemetry: TelemetryService) -> None:
        super().__init__(
            model,
            icon="fa fa-chart-line",
            menu_label="MCP Calls",
            display_name="MCP Call",
        )
        self.telemetry = telemetry

    def can_create(self, _request: Request) -> bool:
        return False

    def can_edit(self, _request: Request) -> bool:
        return False

    @action(
        name="clear_all",
        text="Clear all logs",
        confirmation="Delete all MCP invocation logs?",
        allow_empty_selection=True,
        dedicated_button=True,
    )
    async def clear_all(self, request: Request, _selection: object) -> None:
        removed = await asyncio.to_thread(self.telemetry.clear)
        flash(request, f"Deleted {removed} invocation log records", "success")


class ManagementConfigView(ModelView):
    row_actions_display_type = RowActionsDisplayType.KEBAB
    page_size = 1
    page_size_options = [1]
    fields = cast(
        Sequence[BaseField],
        (
            "logging_enabled",
            "logging_capture_payloads",
            "logging_retention_days",
            "logging_max_records",
            "file_auto_cleanup_enabled",
            "file_retention_days",
            "file_cleanup_limit",
            "maintenance_interval_minutes",
        ),
    )
    actions = ("cleanup_logs",)

    def __init__(self, model: type[ManagementConfigRecord], telemetry: TelemetryService) -> None:
        super().__init__(
            model,
            icon="fa fa-sliders",
            menu_label="Settings",
            display_name="Settings",
        )
        self.telemetry = telemetry

    def can_create(self, _request: Request) -> bool:
        return False

    def can_delete(self, _request: Request) -> bool:
        return False

    async def before_edit(
        self,
        request: Request,
        data: dict[str, object],
        obj: ManagementConfigRecord,
    ) -> None:
        del request
        values = {
            "logging_enabled": data.get("logging_enabled", obj.logging_enabled),
            "logging_capture_payloads": data.get(
                "logging_capture_payloads", obj.logging_capture_payloads
            ),
            "logging_retention_days": data.get(
                "logging_retention_days", obj.logging_retention_days
            ),
            "logging_max_records": data.get("logging_max_records", obj.logging_max_records),
            "file_auto_cleanup_enabled": data.get(
                "file_auto_cleanup_enabled", obj.file_auto_cleanup_enabled
            ),
            "file_retention_days": data.get("file_retention_days", obj.file_retention_days),
            "file_cleanup_limit": data.get("file_cleanup_limit", obj.file_cleanup_limit),
            "maintenance_interval_minutes": data.get(
                "maintenance_interval_minutes", obj.maintenance_interval_minutes
            ),
        }
        config = ManagementConfig.model_validate(values)
        data.update(config.model_dump())

    @action(
        name="cleanup_logs",
        text="Apply log retention now",
        allow_empty_selection=True,
        dedicated_button=True,
    )
    async def cleanup_logs(self, request: Request, _selection: object) -> None:
        removed = await asyncio.to_thread(self.telemetry.cleanup)
        flash(request, f"Removed {removed} expired invocation log records", "success")


class FilesView(CustomView):
    menu_label = "Files"
    icon = "fa fa-folder-open"
    path = "/files"

    def __init__(self, files: FileAdminStore) -> None:
        super().__init__()
        self.files = files

    @route("")
    async def index(self, request: Request) -> Response:
        query = request.query_params.get("q", "")
        sort_by = request.query_params.get("sort", "created_at")
        sort_order = request.query_params.get("order", "desc").casefold()
        allowed_sorts = {"name", "mime_type", "size_bytes", "created_at", "reference_count"}
        if sort_by not in allowed_sorts:
            sort_by = "created_at"
        if sort_order not in {"asc", "desc"}:
            sort_order = "desc"
        listing, stats = await asyncio.gather(
            asyncio.to_thread(
                self.files.list,
                query=query,
                limit=250,
                sort_by=sort_by,
                sort_order=sort_order,
            ),
            asyncio.to_thread(self.files.stats),
        )
        base_url = "/admin/files"
        sort_urls = {
            field: f"{base_url}?{urllib.parse.urlencode({'q': query, 'sort': field, 'order': 'desc' if sort_by == field and sort_order == 'asc' else 'asc'})}"
            for field in allowed_sorts
        }
        return self.templates.TemplateResponse(
            request=request,
            name="management_files.html",
            context={
                "title": "Files",
                "listing": listing,
                "stats": stats,
                "query": query,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "sort_urls": sort_urls,
                "base_url": base_url,
            },
        )

    @route("/upload", methods=["POST"])
    async def upload(self, request: Request) -> Response:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "file") or not hasattr(upload, "filename"):
            flash(request, "Choose a file to upload", "error")
            return RedirectResponse("/admin/files", status_code=303)
        name = str(getattr(upload, "filename", "upload.bin") or "upload.bin")
        content_type = str(getattr(upload, "content_type", "") or "")
        try:
            await asyncio.to_thread(
                self.files.upload,
                getattr(upload, "file"),
                name=name,
                mime_type=content_type,
            )
        except Exception as exc:
            flash(request, f"Upload failed: {exc}", "error")
        else:
            flash(request, f"Uploaded {name}", "success")
        return RedirectResponse("/admin/files", status_code=303)

    @route("/detail/{file_id:path}")
    async def detail(self, request: Request) -> Response:
        file_id = request.path_params["file_id"]
        try:
            info = await asyncio.to_thread(self.files.info, file_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return self.templates.TemplateResponse(
            request=request,
            name="management_file_detail.html",
            context={"title": "File details", "info": info, "base_url": "/admin/files"},
        )

    @route("/download/{file_id:path}")
    async def download(self, request: Request) -> Response:
        file_id = request.path_params["file_id"]
        try:
            info = await asyncio.to_thread(self.files.info, file_id)
            path = await asyncio.to_thread(self.files.path_for, file_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        name = str(info.get("name") or "download.bin")
        mime_type = str(info.get("mime_type") or "application/octet-stream")
        return FileResponse(path, filename=name, media_type=mime_type)

    @route("/delete", methods=["POST"])
    async def delete_file(self, request: Request) -> Response:
        form = await request.form()
        file_id = str(form.get("file_id", "")).strip()
        force = str(form.get("force", "")).lower() in {"1", "true", "on", "yes"}
        try:
            await asyncio.to_thread(self.files.delete, file_id, force=force)
        except Exception as exc:
            flash(request, f"Delete failed: {exc}", "error")
        else:
            flash(request, f"Deleted {file_id}", "success")
        return RedirectResponse("/admin/files", status_code=303)

    @route("/cleanup", methods=["POST"])
    async def cleanup(self, request: Request) -> Response:
        form = await request.form()
        dry_run = str(form.get("dry_run", "")).lower() in {"1", "true", "on", "yes"}
        try:
            retention_days = int(str(form.get("retention_days", "30")))
            limit = int(str(form.get("limit", "1000")))
            if not 1 <= retention_days <= 3650:
                raise ValueError("retention days must be between 1 and 3650")
            if not 1 <= limit <= 10_000:
                raise ValueError("cleanup limit must be between 1 and 10000")
            result = await asyncio.to_thread(
                self.files.cleanup,
                retention_days=retention_days,
                limit=limit,
                dry_run=dry_run,
            )
        except Exception as exc:
            flash(request, f"Cleanup failed: {exc}", "error")
        else:
            mode = "Would remove" if dry_run else "Removed"
            flash(request, f"{mode} {result.get('count', 0)} files", "success")
        return RedirectResponse("/admin/files", status_code=303)


def _dashboard(engine: Engine, files: FileAdminStore) -> CustomView:
    async def count(model: type[object], *_filters: object) -> int:
        statement = select(func.count()).select_from(model)
        for criterion in _filters:
            statement = statement.where(criterion)
        return await asyncio.to_thread(_scalar, engine, statement)

    async def count_accounts(_request: Request) -> int:
        github, gitlab = await asyncio.gather(
            count(GitHubAccountRecord, GitHubAccountRecord.enabled.is_(True)),
            count(GitLabAccountRecord, GitLabAccountRecord.enabled.is_(True)),
        )
        return github + gitlab

    async def count_github(_request: Request) -> int:
        return await count(GitHubAccountRecord, GitHubAccountRecord.enabled.is_(True))

    async def count_gitlab(_request: Request) -> int:
        return await count(GitLabAccountRecord, GitLabAccountRecord.enabled.is_(True))

    async def count_calls(_request: Request) -> int:
        return await count(InvocationRecord)

    async def count_errors(_request: Request) -> int:
        return await count(InvocationRecord, InvocationRecord.status == "error")

    async def average_duration(_request: Request) -> int:
        return await asyncio.to_thread(
            _scalar,
            engine,
            select(func.avg(InvocationRecord.duration_ms)),
        )

    async def stored_files(_request: Request) -> int:
        stats = await asyncio.to_thread(files.stats)
        return int(stats.get("files", 0))

    async def storage_used(_request: Request) -> str:
        stats = await asyncio.to_thread(files.stats)
        return str(stats.get("size_display", "0 B"))

    async def error_rate(_request: Request) -> float:
        calls, errors = await asyncio.gather(count_calls(_request), count_errors(_request))
        return round((errors / calls) * 100, 1) if calls else 0.0

    return CustomView(
        menu_label="Dashboard",
        icon="fa fa-home",
        widget=CardRowWidget(
            children=[
                Col(
                    StatWidget(title="Active accounts", value_callback=count_accounts),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="GitHub accounts", value_callback=count_github),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="GitLab accounts", value_callback=count_gitlab),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="MCP calls", value_callback=count_calls),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Errors", value_callback=count_errors),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Error rate (%)", value_callback=error_rate),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Average duration (ms)", value_callback=average_duration),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Stored files", value_callback=stored_files),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
                Col(
                    StatWidget(title="Storage used", value_callback=storage_used),
                    breakpoints=Breakpoints(default=12, sm=6, md=4, xl=3),
                ),
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
    telemetry: TelemetryService,
    files: FileAdminStore,
) -> Admin:
    admin = Admin(
        engine,
        title="MCP Management",
        base_url="/admin",
        auth_provider=ManagementAuthProvider(settings),
        secret_key=settings.session_secret,
        index_view=_dashboard(engine, files),
        theme=_CompactTheme(),
        templates_dir=str(Path(__file__).with_name("templates")),
    )
    admin.add_view(FilesView(files))
    admin.add_view(
        GitHubAccountView(
            GitHubAccountRecord,
            cipher,
            accounts,
            icon="fa-brands fa-github",
            label="GitHub Accounts",
        )
    )
    admin.add_view(
        GitLabAccountView(
            GitLabAccountRecord,
            cipher,
            accounts,
            icon="fa-brands fa-gitlab",
            label="GitLab Accounts",
        )
    )
    admin.add_view(InvocationView(InvocationRecord, telemetry))
    admin.add_view(ManagementConfigView(ManagementConfigRecord, telemetry))
    return admin
