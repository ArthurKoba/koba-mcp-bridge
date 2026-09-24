from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from management.domain.accounts import Account, AuthType, Provider
from management.domain.configuration import ManagementConfig
from management.domain.telemetry import Invocation

from .database import (
    GitHubAccountRecord,
    GitLabAccountRecord,
    InvocationRecord,
    ManagementConfigRecord,
)


class SqlAlchemyAccountRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _github_domain(record: GitHubAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.GITHUB,
            auth_type=AuthType(record.auth_type),
            label=record.label,
            base_url="https://api.github.com",
            external_id=record.app_id,
            verify_tls=True,
            ca_cert_pem="",
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _gitlab_domain(record: GitLabAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.GITLAB,
            auth_type=AuthType(record.auth_type),
            label=record.label,
            base_url=record.base_url,
            external_id="",
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def list(
        self,
        *,
        provider: Provider | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]:
        accounts: list[Account] = []
        with self.sessions() as session:
            if provider in {None, Provider.GITHUB}:
                stmt = select(GitHubAccountRecord)
                if enabled_only:
                    stmt = stmt.where(GitHubAccountRecord.enabled.is_(True))
                accounts.extend(self._github_domain(row) for row in session.scalars(stmt).all())
            if provider in {None, Provider.GITLAB}:
                stmt = select(GitLabAccountRecord)
                if enabled_only:
                    stmt = stmt.where(GitLabAccountRecord.enabled.is_(True))
                accounts.extend(self._gitlab_domain(row) for row in session.scalars(stmt).all())
        return sorted(accounts, key=lambda item: (item.provider.value, item.alias))

    def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account:
        value = selector.strip()
        if not value:
            raise KeyError("account selector is required")
        with self.sessions() as session:
            if provider is Provider.GITHUB:
                stmt = select(GitHubAccountRecord).where(
                    or_(
                        GitHubAccountRecord.id == value,
                        GitHubAccountRecord.alias == value.casefold(),
                    )
                )
                if enabled_only:
                    stmt = stmt.where(GitHubAccountRecord.enabled.is_(True))
                record = session.scalar(stmt)
                if record is None:
                    raise KeyError(f"GitHub account not found: {selector}")
                return self._github_domain(record)

            stmt = select(GitLabAccountRecord).where(
                or_(
                    GitLabAccountRecord.id == value,
                    GitLabAccountRecord.alias == value.casefold(),
                )
            )
            if enabled_only:
                stmt = stmt.where(GitLabAccountRecord.enabled.is_(True))
            record = session.scalar(stmt)
            if record is None:
                raise KeyError(f"GitLab account not found: {selector}")
            return self._gitlab_domain(record)

    def save(self, account: Account, *, encrypted_credential: str | None = None) -> Account:
        with self.sessions.begin() as session:
            if account.provider is Provider.GITHUB:
                record = session.get(GitHubAccountRecord, account.id)
                if record is None:
                    record = GitHubAccountRecord(id=account.id)
                    session.add(record)
                record.alias = account.alias
                record.auth_type = account.auth_type.value
                record.label = account.label
                record.app_id = account.external_id
                record.enabled = account.enabled
            else:
                record = session.get(GitLabAccountRecord, account.id)
                if record is None:
                    record = GitLabAccountRecord(id=account.id)
                    session.add(record)
                record.alias = account.alias
                record.auth_type = account.auth_type.value
                record.label = account.label
                record.base_url = account.base_url
                record.verify_tls = account.verify_tls
                record.ca_cert_pem = account.ca_cert_pem
                record.enabled = account.enabled
            record.created_at = account.created_at
            record.updated_at = account.updated_at
            if encrypted_credential is not None:
                record.encrypted_credential = encrypted_credential
        return account

    def delete(self, account_id: str, *, provider: Provider) -> None:
        model = GitHubAccountRecord if provider is Provider.GITHUB else GitLabAccountRecord
        with self.sessions.begin() as session:
            record = session.get(model, account_id)
            if record is not None:
                session.delete(record)

    def set_credential(self, account_id: str, encrypted_value: str, *, provider: Provider) -> None:
        model = GitHubAccountRecord if provider is Provider.GITHUB else GitLabAccountRecord
        with self.sessions.begin() as session:
            record = session.get(model, account_id)
            if record is None:
                raise KeyError(f"account not found: {account_id}")
            record.encrypted_credential = encrypted_value

    def credential(self, account_id: str, *, provider: Provider) -> str:
        model = GitHubAccountRecord if provider is Provider.GITHUB else GitLabAccountRecord
        with self.sessions() as session:
            record = session.get(model, account_id)
            if record is None or not record.encrypted_credential:
                raise KeyError(f"credential not configured for account: {account_id}")
            return record.encrypted_credential


class SqlAlchemyInvocationRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _config(session: Session) -> ManagementConfigRecord:
        config = session.get(ManagementConfigRecord, 1)
        if config is None:
            config = ManagementConfigRecord(id=1)
            session.add(config)
            session.flush()
        return config

    @staticmethod
    def _cleanup_in_session(session: Session, config: ManagementConfigRecord) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max(config.logging_retention_days, 1))
        removed = session.execute(
            delete(InvocationRecord).where(InvocationRecord.occurred_at < cutoff)
        ).rowcount or 0
        count = session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
        overflow = count - max(config.logging_max_records, 100)
        if overflow > 0:
            stale_ids = (
                select(InvocationRecord.id)
                .order_by(InvocationRecord.occurred_at.asc())
                .limit(overflow)
            )
            removed += session.execute(
                delete(InvocationRecord).where(InvocationRecord.id.in_(stale_ids))
            ).rowcount or 0
        return int(removed)

    def append(self, invocation: Invocation) -> None:
        with self.sessions.begin() as session:
            config = self._config(session)
            if not config.logging_enabled:
                return
            payloads = config.logging_capture_payloads
            session.add(
                InvocationRecord(
                    id=invocation.id,
                    request_id=invocation.request_id,
                    module=invocation.module,
                    tool=invocation.tool,
                    account_id=invocation.account_id,
                    provider=invocation.provider,
                    status=invocation.status,
                    duration_ms=invocation.duration_ms,
                    error_type=invocation.error_type,
                    arguments_json=invocation.arguments_json if payloads else "",
                    result_json=invocation.result_json if payloads else "",
                    error_message=invocation.error_message if payloads else "",
                    occurred_at=invocation.occurred_at,
                )
            )
            self._cleanup_in_session(session, config)

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        size = max(1, min(limit, 1000))
        with self.sessions() as session:
            rows = session.scalars(
                select(InvocationRecord).order_by(InvocationRecord.occurred_at.desc()).limit(size)
            ).all()
            return [
                Invocation(
                    id=row.id,
                    request_id=row.request_id,
                    module=row.module,
                    tool=row.tool,
                    account_id=row.account_id,
                    provider=row.provider,
                    status=row.status,
                    duration_ms=row.duration_ms,
                    error_type=row.error_type,
                    arguments_json=row.arguments_json,
                    result_json=row.result_json,
                    error_message=row.error_message,
                    occurred_at=row.occurred_at,
                )
                for row in rows
            ]

    def clear(self) -> int:
        with self.sessions.begin() as session:
            count = session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
            session.execute(delete(InvocationRecord))
            return int(count)

    def cleanup(self) -> int:
        with self.sessions.begin() as session:
            return self._cleanup_in_session(session, self._config(session))


class SqlAlchemyManagementConfigRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def get(self) -> ManagementConfig:
        with self.sessions.begin() as session:
            record = session.get(ManagementConfigRecord, 1)
            if record is None:
                record = ManagementConfigRecord(id=1)
                session.add(record)
                session.flush()
            return ManagementConfig(
                logging_enabled=record.logging_enabled,
                logging_capture_payloads=record.logging_capture_payloads,
                logging_retention_days=record.logging_retention_days,
                logging_max_records=record.logging_max_records,
                file_auto_cleanup_enabled=record.file_auto_cleanup_enabled,
                file_retention_days=record.file_retention_days,
                file_cleanup_limit=record.file_cleanup_limit,
                maintenance_interval_minutes=record.maintenance_interval_minutes,
            )
