from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from control_plane.domain.accounts import Account, AccountRole, AuthType, Provider
from control_plane.domain.telemetry import Invocation

from .database import AccountRecord, InvocationRecord


class SqlAlchemyAccountRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _domain(record: AccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider(record.provider),
            role=AccountRole(record.role),
            auth_type=AuthType(record.auth_type),
            label=record.label,
            base_url=record.base_url,
            external_id=record.external_id,
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
        role: AccountRole | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]:
        with self.sessions() as session:
            stmt = select(AccountRecord)
            if provider is not None:
                stmt = stmt.where(AccountRecord.provider == provider.value)
            if role is not None:
                stmt = stmt.where(AccountRecord.role == role.value)
            if enabled_only:
                stmt = stmt.where(AccountRecord.enabled.is_(True))
            stmt = stmt.order_by(AccountRecord.alias.asc())
            return [self._domain(item) for item in session.scalars(stmt).all()]

    def get(
        self,
        selector: str,
        *,
        provider: Provider | None = None,
        role: AccountRole | None = None,
        enabled_only: bool = True,
    ) -> Account:
        value = selector.strip()
        if not value:
            raise KeyError("account selector is required")
        with self.sessions() as session:
            stmt = select(AccountRecord).where(
                or_(AccountRecord.id == value, AccountRecord.alias == value.casefold())
            )
            if provider is not None:
                stmt = stmt.where(AccountRecord.provider == provider.value)
            if role is not None:
                stmt = stmt.where(AccountRecord.role == role.value)
            if enabled_only:
                stmt = stmt.where(AccountRecord.enabled.is_(True))
            record = session.scalar(stmt)
            if record is None:
                raise KeyError(f"account not found: {selector}")
            return self._domain(record)

    def save(self, account: Account, *, encrypted_credential: str | None = None) -> Account:
        with self.sessions.begin() as session:
            record = session.get(AccountRecord, account.id)
            if record is None:
                record = AccountRecord(id=account.id)
                session.add(record)
            record.alias = account.alias
            record.provider = account.provider.value
            record.role = account.role.value
            record.auth_type = account.auth_type.value
            record.label = account.label
            record.base_url = account.base_url
            record.external_id = account.external_id
            record.verify_tls = account.verify_tls
            record.ca_cert_pem = account.ca_cert_pem
            record.enabled = account.enabled
            record.created_at = account.created_at
            record.updated_at = account.updated_at
            if encrypted_credential is not None:
                record.encrypted_credential = encrypted_credential
        return account

    def delete(self, account_id: str) -> None:
        with self.sessions.begin() as session:
            record = session.get(AccountRecord, account_id)
            if record is not None:
                session.delete(record)

    def set_credential(self, account_id: str, encrypted_value: str) -> None:
        with self.sessions.begin() as session:
            record = session.get(AccountRecord, account_id)
            if record is None:
                raise KeyError(f"account not found: {account_id}")
            record.encrypted_credential = encrypted_value

    def credential(self, account_id: str) -> str:
        with self.sessions() as session:
            record = session.get(AccountRecord, account_id)
            if record is None or not record.encrypted_credential:
                raise KeyError(f"credential not configured for account: {account_id}")
            return record.encrypted_credential


class SqlAlchemyInvocationRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def append(self, invocation: Invocation) -> None:
        with self.sessions.begin() as session:
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
                    occurred_at=invocation.occurred_at,
                )
            )

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        size = max(1, min(limit, 1000))
        with self.sessions() as session:
            rows = session.scalars(
                select(InvocationRecord)
                .order_by(InvocationRecord.occurred_at.desc())
                .limit(size)
            ).all()
            return [
                Invocation.model_validate(
                    {
                        "id": row.id,
                        "request_id": row.request_id,
                        "module": row.module,
                        "tool": row.tool,
                        "account_id": row.account_id,
                        "provider": row.provider,
                        "status": row.status,
                        "duration_ms": row.duration_ms,
                        "error_type": row.error_type,
                        "occurred_at": row.occurred_at,
                    }
                )
                for row in rows
            ]
