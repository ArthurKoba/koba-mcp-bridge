from __future__ import annotations

import urllib.parse

from pydantic import ConfigDict

from .models import JsonObject, StrictModel
from .secret_errors import SecretError


class InfisicalConfig(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    host: str
    project_id: str
    client_id: str
    client_secret: str
    environment: str = "prod"
    base_path: str = "/"
    verify_tls: bool = True
    ca_file: str = ""
    client_id_source: str = ""
    client_secret_source: str = ""

    def configured(self) -> bool:
        return bool(self.host and self.project_id and self.client_id and self.client_secret)

    def validate_config(self) -> None:
        if not self.host:
            raise SecretError("INFISICAL_HOST is not configured")
        parsed = urllib.parse.urlsplit(self.host)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SecretError("INFISICAL_HOST must be an http(s) origin")
        if parsed.path not in {"", "/"}:
            raise SecretError("INFISICAL_HOST must not contain an API path")
        if not self.project_id:
            raise SecretError("INFISICAL_PROJECT_ID is not configured")
        if not self.client_id:
            raise SecretError("Infisical client ID is not configured")
        if not self.client_secret:
            raise SecretError("Infisical client secret is not configured")

    def public(self) -> JsonObject:
        return {
            "configured": self.configured(),
            "host": self.host or None,
            "project_id": self.project_id or None,
            "environment": self.environment,
            "base_path": self.base_path,
            "verify_tls": self.verify_tls,
            "ca_file": self.ca_file or None,
            "client_id_source": self.client_id_source or None,
            "client_secret_source": self.client_secret_source or None,
        }
