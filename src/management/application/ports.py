from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from management.domain.accounts import Account, Provider
from management.domain.configuration import ManagementConfig
from management.domain.telemetry import Invocation


class AccountRepository(Protocol):
    def list(
        self,
        *,
        provider: Provider | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]: ...

    def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account: ...

    def save(self, account: Account, *, encrypted_credential: str | None = None) -> Account: ...

    def delete(self, account_id: str, *, provider: Provider) -> None: ...

    def set_credential(
        self,
        account_id: str,
        encrypted_value: str,
        *,
        provider: Provider,
    ) -> None: ...

    def credential(self, account_id: str, *, provider: Provider) -> str: ...


class InvocationRepository(Protocol):
    def append(self, invocation: Invocation) -> None: ...

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]: ...

    def clear(self) -> int: ...

    def cleanup(self) -> int: ...


class ManagementConfigRepository(Protocol):
    def get(self) -> ManagementConfig: ...


class CredentialCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class ConnectionVerifier(Protocol):
    def verify(self, account: Account, credential: str) -> dict[str, object]: ...
