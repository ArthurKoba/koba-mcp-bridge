from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from common.account_contracts import AccountPublic, ResolvedAccount
from common.models import JsonObject, json_object
from management.domain.accounts import Account, Provider
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

    def list(self, *, provider: Provider | None = None) -> list[AccountPublic]:
        return [
            AccountPublic.model_validate(account.public())
            for account in self.repository.list(provider=provider, enabled_only=False)
        ]

    def get(self, selector: str, *, provider: Provider) -> Account:
        return self.repository.get(selector, provider=provider)

    def resolve(self, selector: str, *, provider: Provider) -> ResolvedAccount:
        account = self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(
            self.repository.credential(account.id, provider=provider)
        )
        return ResolvedAccount.model_validate({**account.public(), "credential": credential})

    def create(self, account: Account, *, credential: str) -> Account:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        return self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret),
        )

    def update(self, account: Account) -> Account:
        account.updated_at = datetime.now(UTC)
        return self.repository.save(account)

    def set_credential(self, account_id: str, credential: str, *, provider: Provider) -> None:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        self.repository.set_credential(
            account_id,
            self.cipher.encrypt(secret),
            provider=provider,
        )

    def delete(self, account_id: str, *, provider: Provider) -> None:
        self.repository.delete(account_id, provider=provider)

    def verify(self, selector: str, *, provider: Provider) -> JsonObject:
        account = self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(
            self.repository.credential(account.id, provider=provider)
        )
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

    def clear(self) -> int:
        return self.repository.clear()

    def cleanup(self) -> int:
        return self.repository.cleanup()
