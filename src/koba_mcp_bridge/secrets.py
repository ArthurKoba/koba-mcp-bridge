from __future__ import annotations

import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SecretError(RuntimeError):
    """Raised when Koba cannot resolve a configured secret reference."""


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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


@dataclass(frozen=True)
class InfisicalConfig:
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
    def from_env(cls) -> InfisicalConfig:
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
            verify_tls=_env_bool("INFISICAL_VERIFY_TLS", True),
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

    def validate(self) -> None:
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

    def public(self) -> dict[str, Any]:
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


@dataclass(frozen=True)
class SecretReference:
    raw: str
    scheme: str
    environment: str = ""
    secret_path: str = "/"
    secret_name: str = ""
    project_id: str = ""
    env_name: str = ""
    file_path: str = ""

    @classmethod
    def parse(cls, value: str) -> SecretReference:
        raw = value.strip()
        if not raw:
            raise SecretError("secret reference must not be empty")
        parsed = urllib.parse.urlsplit(raw)
        scheme = parsed.scheme.casefold()
        if scheme == "env":
            name = (parsed.netloc + parsed.path).strip("/")
            if not name:
                raise SecretError("env secret reference must name an environment variable")
            return cls(raw=raw, scheme=scheme, env_name=name)

        if scheme == "file":
            path = urllib.parse.unquote(parsed.path)
            if parsed.netloc and parsed.netloc not in {"", "localhost"}:
                path = f"//{parsed.netloc}{path}"
            candidate = Path(path)
            if not candidate.is_absolute():
                raise SecretError("file secret reference must use an absolute path")
            return cls(raw=raw, scheme=scheme, file_path=str(candidate))

        if scheme == "infisical":
            environment = urllib.parse.unquote(parsed.netloc).strip()
            if not environment:
                raise SecretError("Infisical reference must include environment")
            secret_name = urllib.parse.unquote(parsed.fragment).strip()
            if not secret_name:
                raise SecretError("Infisical reference must include #SECRET_NAME")
            path = urllib.parse.unquote(parsed.path) or "/"
            if not path.startswith("/"):
                path = "/" + path
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
            project_id = ""
            for key in ("projectId", "project_id"):
                values = query.get(key)
                if values:
                    project_id = values[-1].strip()
                    break
            return cls(
                raw=raw,
                scheme=scheme,
                environment=environment,
                secret_path=path,
                secret_name=secret_name,
                project_id=project_id,
            )

        raise SecretError(
            "secret reference scheme must be env://, file://, or infisical://"
        )

    def public(self) -> dict[str, Any]:
        if self.scheme == "env":
            return {"scheme": "env", "env_name": self.env_name}
        if self.scheme == "file":
            return {"scheme": "file", "file_path": self.file_path}
        return {
            "scheme": "infisical",
            "environment": self.environment,
            "secret_path": self.secret_path,
            "secret_name": self.secret_name,
            "project_id": self.project_id or None,
        }


class InfisicalClient:
    def __init__(self, config: InfisicalConfig | None = None) -> None:
        self.config = config or InfisicalConfig.from_env()
        self._access_token = ""
        self._access_token_expiry = 0.0
        self._lock = threading.Lock()

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not self.config.host.startswith("https://"):
            return None
        if not self.config.verify_tls:
            return ssl._create_unverified_context()
        if self.config.ca_file:
            return ssl.create_default_context(cafile=self.config.ca_file)
        return ssl.create_default_context()

    def _json_request(
        self,
        request: urllib.request.Request,
        *,
        timeout: float = 30,
    ) -> tuple[int, dict[str, Any]]:
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=self._ssl_context(),
            ) as response:
                raw = response.read()
                data = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(data, dict):
                    raise SecretError("Infisical returned a non-object JSON response")
                return response.status, data
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = raw[:2048].decode("utf-8", "replace")
            raise SecretError(f"Infisical API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SecretError(f"Infisical API transport error: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise SecretError("Infisical returned invalid JSON") from exc

    def _login_locked(self) -> str:
        self.config.validate()
        now = time.time()
        if self._access_token and self._access_token_expiry > now + 60:
            return self._access_token

        payload = urllib.parse.urlencode(
            {
                "clientId": self.config.client_id,
                "clientSecret": self.config.client_secret,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.config.host + "/api/v1/auth/universal-auth/login",
            data=payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "koba-mcp-bridge",
            },
        )
        _, data = self._json_request(request)
        access_token = str(data.get("accessToken", "")).strip()
        expires_in = data.get("expiresIn", 0)
        try:
            ttl = float(expires_in)
        except (TypeError, ValueError):
            ttl = 0
        if not access_token or ttl <= 0:
            raise SecretError("Infisical Universal Auth response is incomplete")
        self._access_token = access_token
        self._access_token_expiry = now + ttl
        return access_token

    def access_token(self) -> str:
        with self._lock:
            return self._login_locked()

    def list_folders(
        self,
        *,
        environment: str,
        secret_path: str = "/",
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        env = environment.strip()
        path = secret_path.strip() or "/"
        if not env:
            raise SecretError("Infisical environment is required")
        if not path.startswith("/"):
            path = "/" + path
        project = project_id.strip() or self.config.project_id
        if not project:
            raise SecretError("Infisical project id is not configured")

        query = urllib.parse.urlencode(
            {
                "workspaceId": project,
                "environment": env,
                "path": path,
                "recursive": "false",
            }
        )
        request = urllib.request.Request(
            self.config.host + "/api/v1/folders?" + query,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token()}",
                "User-Agent": "koba-mcp-bridge",
            },
        )
        _, data = self._json_request(request)
        folders = data.get("folders")
        if not isinstance(folders, list):
            raise SecretError("Infisical folder response has no folders list")
        return [item for item in folders if isinstance(item, dict)]

    def get_secret(
        self,
        secret_name: str,
        *,
        environment: str,
        secret_path: str = "/",
        project_id: str = "",
    ) -> tuple[str, dict[str, Any]]:
        name = secret_name.strip()
        env = environment.strip()
        if not name or not env:
            raise SecretError("Infisical secret name and environment are required")
        path = secret_path.strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        project = project_id.strip() or self.config.project_id
        if not project:
            raise SecretError("Infisical project id is not configured")

        query = urllib.parse.urlencode(
            {
                "projectId": project,
                "environment": env,
                "secretPath": path,
            }
        )
        request = urllib.request.Request(
            self.config.host
            + "/api/v4/secrets/"
            + urllib.parse.quote(name, safe="")
            + "?"
            + query,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token()}",
                "User-Agent": "koba-mcp-bridge",
            },
        )
        _, data = self._json_request(request)
        secret = data.get("secret")
        if not isinstance(secret, dict):
            raise SecretError("Infisical secret response has no secret object")
        value = secret.get("secretValue")
        if not isinstance(value, str):
            raise SecretError("Infisical secret response has no string secretValue")
        metadata = {
            "id": secret.get("id"),
            "secret_name": secret.get("secretKey", name),
            "secret_path": secret.get("secretPath", path),
            "environment": env,
            "project_id": project,
            "version": secret.get("version"),
            "updated_at": secret.get("updatedAt"),
        }
        return value, metadata

    def status(self, *, authenticate: bool = False) -> dict[str, Any]:
        result = self.config.public()
        result["provider"] = "infisical"
        if authenticate:
            if not self.config.configured():
                result["authenticated"] = False
                return result
            self.access_token()
            result["authenticated"] = True
            result["access_token_cached"] = bool(self._access_token)
            result["access_token_expires_in"] = max(
                0,
                int(self._access_token_expiry - time.time()),
            )
        return result


class SecretResolver:
    def __init__(self, infisical: InfisicalClient | None = None) -> None:
        self.infisical = infisical or InfisicalClient()

    def _config_path(self, relative_path: str) -> str:
        base = self.infisical.config.base_path.strip("/")
        relative = relative_path.strip("/")
        parts = [part for part in (base, relative) if part]
        return "/" + "/".join(parts) if parts else "/"

    def get(self, relative_path: str, secret_name: str) -> str:
        value, _metadata = self.infisical.get_secret(
            secret_name,
            environment=self.infisical.config.environment,
            secret_path=self._config_path(relative_path),
        )
        return value

    def list_folders(self, relative_path: str) -> list[dict[str, Any]]:
        return self.infisical.list_folders(
            environment=self.infisical.config.environment,
            secret_path=self._config_path(relative_path),
        )

    def resolve(self, reference: str) -> str:
        ref = SecretReference.parse(reference)
        if ref.scheme == "env":
            value = os.getenv(ref.env_name, "")
            if not value:
                raise SecretError(
                    f"environment secret {ref.env_name!r} is not configured"
                )
            return value

        if ref.scheme == "file":
            try:
                value = Path(ref.file_path).read_text(encoding="utf-8")
            except OSError as exc:
                raise SecretError("secret file cannot be read") from exc
            if not value:
                raise SecretError("secret file is empty")
            return value.rstrip("\r\n")

        value, _metadata = self.infisical.get_secret(
            ref.secret_name,
            environment=ref.environment,
            secret_path=ref.secret_path,
            project_id=ref.project_id,
        )
        return value

    def check(self, reference: str) -> dict[str, Any]:
        ref = SecretReference.parse(reference)
        self.resolve(reference)
        return {
            "available": True,
            "reference": ref.public(),
        }


_default_resolver = SecretResolver()


def resolve_secret(reference: str) -> str:
    """Resolve an explicit secret reference for internal connector use."""
    return _default_resolver.resolve(reference)


def resolve_config_secret(relative_path: str, secret_name: str) -> str:
    """Resolve one convention-based Infisical secret under the configured base path."""
    return _default_resolver.get(relative_path, secret_name)


def list_config_folders(relative_path: str) -> list[dict[str, Any]]:
    """List immediate Infisical folders under one convention-based path."""
    return _default_resolver.list_folders(relative_path)


def secret_reference_available(reference: str) -> dict[str, Any]:
    return _default_resolver.check(reference)


def secrets_status(authenticate: bool = False) -> dict[str, Any]:
    return _default_resolver.infisical.status(authenticate=authenticate)
