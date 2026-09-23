from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from pydantic import ConfigDict

from .config import env_bool
from .models import JsonObject, StrictModel
from .secret_errors import SecretError


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 3600.0,
) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SecretError(f"{name} must be a number") from exc
    if value < minimum or value > maximum:
        raise SecretError(
            f"{name} must be between {minimum:g} and {maximum:g} seconds"
        )
    return value


def _read_bootstrap_value(env_name: str, file_env_name: str) -> tuple[str, str]:
    raw = os.getenv(env_name, "").strip()
    file_path = os.getenv(file_env_name, "").strip()
    if raw and file_path:
        raise SecretError(f"configure only one of {env_name} or {file_env_name}")
    if raw:
        return raw, f"env:{env_name}"
    if file_path:
        path = Path(file_path)
        if not path.is_absolute():
            raise SecretError(f"{file_env_name} must point to an absolute path")
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SecretError(f"unable to read {file_env_name}") from exc
        if not value:
            raise SecretError(f"{file_env_name} points to an empty file")
        return value, f"file:{file_path}"
    return "", ""


class InfisicalConfig(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )
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

    @classmethod
    def from_env(cls) -> "InfisicalConfig":
        host = os.getenv("INFISICAL_HOST", "").strip().rstrip("/")
        project_id = os.getenv("INFISICAL_PROJECT_ID", "").strip()
        environment = os.getenv("INFISICAL_ENVIRONMENT", "prod").strip() or "prod"
        base_path = os.getenv("INFISICAL_BASE_PATH", "/").strip() or "/"
        if not base_path.startswith("/"):
            base_path = "/" + base_path
        base_path = "/" + base_path.strip("/") if base_path.strip("/") else "/"
        client_id, client_id_source = _read_bootstrap_value(
            "INFISICAL_CLIENT_ID",
            "INFISICAL_CLIENT_ID_FILE",
        )
        client_secret, client_secret_source = _read_bootstrap_value(
            "INFISICAL_CLIENT_SECRET",
            "INFISICAL_CLIENT_SECRET_FILE",
        )
        ca_file = os.getenv("INFISICAL_CA_FILE", "").strip()
        if ca_file and not Path(ca_file).is_absolute():
            raise SecretError("INFISICAL_CA_FILE must be an absolute path")
        return cls(
            host=host,
            project_id=project_id,
            client_id=client_id,
            client_secret=client_secret,
            environment=environment,
            base_path=base_path,
            verify_tls=env_bool("INFISICAL_VERIFY_TLS", True),
            ca_file=ca_file,
            client_id_source=client_id_source,
            client_secret_source=client_secret_source,
        )

    def configured(self) -> bool:
        return bool(
            self.host
            and self.project_id
            and self.client_id
            and self.client_secret
        )

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
