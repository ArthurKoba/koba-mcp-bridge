from __future__ import annotations

import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from pydantic import ValidationError

from .infisical_models import (
    InfisicalAuthResponse,
    InfisicalFolderResponse,
    InfisicalSecretResponse,
)
from .models import JsonObject, json_loads, json_object
from .secret_config import InfisicalConfig
from .secret_errors import SecretError


class InfisicalClient:
    def __init__(self, config: InfisicalConfig | None = None) -> None:
        if config is None:
            raise ValueError("InfisicalClient requires explicit InfisicalConfig")
        self.config = config
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
