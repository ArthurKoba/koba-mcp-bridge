from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from control_plane.domain.accounts import Account, AccountRole, Provider
from control_plane.domain.telemetry import Invocation


class AccountRepository(Protocol):
    def list(
        self,
        *,
        provider: Provider | None = None,
        role: AccountRole | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]: ...

    def get(
        self,
        selector: str,
        *,
        provider: Provider | None = None,
        role: AccountRole | None = None,
        enabled_only: bool = True,
    ) -> Account: ...

    def save(self, account: Account, *, encrypted_credential: str | None = None) -> Account: ...

    def delete(self, account_id: str) -> None: ...

    def set_credential(self, account_id: str, encrypted_value: str) -> None: ...

    def credential(self, account_id: str) -> str: ...


class InvocationRepository(Protocol):
    def append(self, invocation: Invocation) -> None: ...

    def recent(self, *, limit: int = 100) -> Sequence[Invocation]: ...


class CredentialCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class ConnectionVerifier(Protocol):
    def verify(self, account: Account, credential: str) -> dict[str, object]: ...
