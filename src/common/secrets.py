from __future__ import annotations

import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError
from .config import env_bool
from .models import (
    JsonObject,
    ProviderModel,
    StrictModel,
    json_loads,
    json_object,
)


class SecretError(RuntimeError):
    """Raised when MCP Bridge cannot resolve a configured secret reference."""


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


class SecretReference(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )
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

    def public(self) -> JsonObject:
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



class InfisicalAuthResponse(ProviderModel):
    access_token: str = Field(alias="accessToken", min_length=1)
    expires_in: float = Field(alias="expiresIn", gt=0)


class InfisicalFolder(ProviderModel):
    name: str = Field(min_length=1)


class InfisicalFolderResponse(ProviderModel):
    folders: list[InfisicalFolder]


class InfisicalSecret(ProviderModel):
    secret_value: str = Field(alias="secretValue")
    id: str | int | None = None
    secret_key: str | None = Field(default=None, alias="secretKey")
    secret_path: str | None = Field(default=None, alias="secretPath")
    version: str | int | None = None
    updated_at: str | None = Field(default=None, alias="updatedAt")


class InfisicalSecretResponse(ProviderModel):
    secret: InfisicalSecret


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
    ) -> tuple[int, JsonObject]:
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=self._ssl_context(),
            ) as response:
                raw = response.read()
                if not raw:
                    return response.status, {}
                data = json_object(
                    json_loads(raw, context="Infisical response"),
                    context="Infisical response",
                )
                return response.status, data
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = raw[:2048].decode("utf-8", "replace")
            raise SecretError(f"Infisical API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SecretError(f"Infisical API transport error: {exc.reason}") from exc
        except ValueError as exc:
            raise SecretError("Infisical returned invalid JSON") from exc

    def _login_locked(self) -> str:
        self.config.validate_config()
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
                "User-Agent": "mcp-bridge",
            },
        )
        _, data = self._json_request(request)
        try:
            auth = InfisicalAuthResponse.model_validate(data)
        except ValidationError as exc:
            raise SecretError("Infisical Universal Auth response is incomplete") from exc
        self._access_token = auth.access_token
        self._access_token_expiry = now + auth.expires_in
        return self._access_token

    def access_token(self) -> str:
        with self._lock:
            return self._login_locked()

    def list_folders(
        self,
        *,
        environment: str,
        secret_path: str = "/",
        project_id: str = "",
    ) -> list[JsonObject]:
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
                "User-Agent": "mcp-bridge",
            },
        )
        _, data = self._json_request(request)
        try:
            response = InfisicalFolderResponse.model_validate(data)
        except ValidationError as exc:
            raise SecretError("Infisical folder response is invalid") from exc
        return [json_object(item.model_dump(mode="json")) for item in response.folders]

    def get_secret(
        self,
        secret_name: str,
        *,
        environment: str,
        secret_path: str = "/",
        project_id: str = "",
    ) -> tuple[str, JsonObject]:
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
                "User-Agent": "mcp-bridge",
            },
        )
        _, data = self._json_request(request)
        try:
            response = InfisicalSecretResponse.model_validate(data)
        except ValidationError as exc:
            raise SecretError("Infisical secret response is invalid") from exc
        secret = response.secret
        metadata: JsonObject = {
            "id": secret.id,
            "secret_name": secret.secret_key or name,
            "secret_path": secret.secret_path or path,
            "environment": env,
            "project_id": project,
            "version": secret.version,
            "updated_at": secret.updated_at,
        }
        return secret.secret_value, metadata

    def status(self, *, authenticate: bool = False) -> JsonObject:
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
    def __init__(
        self,
        infisical: InfisicalClient | None = None,
        *,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self.infisical = infisical or InfisicalClient()
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._secret_cache: dict[
            tuple[str, str, str, str],
            tuple[float, str],
        ] = {}
        self._inflight: dict[
            tuple[str, str, str, str],
            threading.Event,
        ] = {}
        self._cache_lock = threading.Lock()

    def _config_path(self, relative_path: str) -> str:
        base = self.infisical.config.base_path.strip("/")
        relative = relative_path.strip("/")
        parts = [part for part in (base, relative) if part]
        return "/" + "/".join(parts) if parts else "/"

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._secret_cache.clear()

    def _get_infisical_cached(
        self,
        secret_name: str,
        *,
        environment: str,
        secret_path: str,
        project_id: str = "",
    ) -> str:
        name = secret_name.strip()
        env = environment.strip()
        path = secret_path.strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        project = project_id.strip() or self.infisical.config.project_id
        key = (project, env, path, name)

        while True:
            now = time.monotonic()
            leader = False
            with self._cache_lock:
                cached = self._secret_cache.get(key)
                if cached is not None:
                    expires_at, value = cached
                    if expires_at > now:
                        return value
                    self._secret_cache.pop(key, None)

                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    leader = True

            if leader:
                break
            if not event.wait(timeout=30):
                raise SecretError(
                    "timed out waiting for concurrent Infisical secret fetch"
                )

        try:
            value, _metadata = self.infisical.get_secret(
                name,
                environment=env,
                secret_path=path,
                project_id=project,
            )
        except Exception:
            with self._cache_lock:
                event = self._inflight.pop(key, None)
                if event is not None:
                    event.set()
            raise

        with self._cache_lock:
            if self.cache_ttl_seconds > 0:
                self._secret_cache[key] = (
                    time.monotonic() + self.cache_ttl_seconds,
                    value,
                )
            event = self._inflight.pop(key, None)
            if event is not None:
                event.set()
        return value

    def get(self, relative_path: str, secret_name: str) -> str:
        return self._get_infisical_cached(
            secret_name,
            environment=self.infisical.config.environment,
            secret_path=self._config_path(relative_path),
        )

    def list_folders(self, relative_path: str) -> list[JsonObject]:
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

        return self._get_infisical_cached(
            ref.secret_name,
            environment=ref.environment,
            secret_path=ref.secret_path,
            project_id=ref.project_id,
        )

    def check(self, reference: str) -> JsonObject:
        ref = SecretReference.parse(reference)
        self.resolve(reference)
        return {
            "available": True,
            "reference": ref.public(),
        }


_default_resolver = SecretResolver(
    cache_ttl_seconds=_env_float(
        "INFISICAL_CACHE_TTL_SECONDS",
        60.0,
        minimum=0.0,
        maximum=3600.0,
    )
)


def resolve_secret(reference: str) -> str:
    """Resolve an explicit secret reference for internal connector use."""
    return _default_resolver.resolve(reference)


def resolve_config_secret(relative_path: str, secret_name: str) -> str:
    """Resolve one convention-based Infisical secret under the configured base path."""
    return _default_resolver.get(relative_path, secret_name)


def list_config_folders(relative_path: str) -> list[JsonObject]:
    """List immediate Infisical folders under one convention-based path."""
    return _default_resolver.list_folders(relative_path)


def secret_reference_available(reference: str) -> JsonObject:
    return _default_resolver.check(reference)


def secrets_status(authenticate: bool = False) -> JsonObject:
    return _default_resolver.infisical.status(authenticate=authenticate)
