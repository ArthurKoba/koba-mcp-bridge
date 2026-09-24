from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from common.account_contracts import AccountPublic, ResolvedAccount
from common.models import JsonObject, json_object
from management.domain.accounts import Account, AccountRole, Provider
from management.domain.telemetry import Invocation

from .ports import AccountRepository, ConnectionVerifier, CredentialCipher, InvocationRepository


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        cipher: CredentialCipher,
        verifier: ConnectionVerifier,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.verifier = verifier

    def list(
        self,
        *,
        provider: Provider | None = None,
        role: AccountRole | None = None,
    ) -> list[AccountPublic]:
        return [
            AccountPublic.model_validate(account.public())
            for account in self.repository.list(provider=provider, role=role)
        ]

    def get(
        self,
        selector: str,
        *,
        provider: Provider | None = None,
        role: AccountRole | None = None,
    ) -> Account:
        return self.repository.get(selector, provider=provider, role=role)

    def resolve(
        self,
        selector: str,
        *,
        provider: Provider,
        role: AccountRole | None = None,
    ) -> ResolvedAccount:
        account = self.repository.get(selector, provider=provider, role=role)
        credential = self.cipher.decrypt(self.repository.credential(account.id))
        return ResolvedAccount.model_validate(
            {**account.public(), "credential": credential}
        )

    def create(self, account: Account, *, credential: str) -> Account:
        if not credential.strip():
            raise ValueError("credential is required")
        encrypted = self.cipher.encrypt(credential.strip())
        return self.repository.save(account, encrypted_credential=encrypted)

    def update(self, account: Account) -> Account:
        account.updated_at = datetime.now(UTC)
        return self.repository.save(account)

    def replace_credential(self, selector: str, credential: str) -> None:
        account = self.repository.get(selector, enabled_only=False)
        if not credential.strip():
            raise ValueError("credential is required")
        self.repository.set_credential(account.id, self.cipher.encrypt(credential.strip()))

    def delete(self, selector: str) -> None:
        account = self.repository.get(selector, enabled_only=False)
        self.repository.delete(account.id)

    def verify(self, selector: str) -> JsonObject:
        account = self.repository.get(selector)
        credential = self.cipher.decrypt(self.repository.credential(account.id))
        return json_object(
            self.verifier.verify(account, credential),
            context="connection verification result",
        )


class TelemetryService:
    def __init__(self, repository: InvocationRepository) -> None:
        self.repository = repository

    def record(self, invocation: Invocation) -> None:
        self.repository.append(invocation)

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        return self.repository.recent(limit=limit)
