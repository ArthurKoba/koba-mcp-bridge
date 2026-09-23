from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class FernetCredentialCipher:
    def __init__(self, key: str) -> None:
        value = key.strip().encode("ascii")
        if not value:
            raise ValueError("CONTROL_PLANE_ENCRYPTION_KEY is required")
        try:
            self._fernet = Fernet(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("CONTROL_PLANE_ENCRYPTION_KEY must be a Fernet key") from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("stored credential cannot be decrypted with current key") from exc
