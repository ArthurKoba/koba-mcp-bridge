from __future__ import annotations

import http.client
import json
import ssl
import urllib.parse

from common.http_transport import HttpTransportError, PooledHttpTransport
from common.models import JsonObject, JsonValue, json_loads, json_value

from . import credentials
from .errors import GitLabError
from .models import GitLabProfile, GitLabResponse


class GitLabApiClient:
    def __init__(self, profile: GitLabProfile, *, max_connections: int = 4) -> None:
        profile.bind_token_resolver(credentials.resolve_config_secret)
        self.profile = profile
        self.max_connections = max(1, int(max_connections))
        parsed = urllib.parse.urlsplit(profile.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise GitLabError(
                f"profile {profile.profile_id!r} has invalid base_url"
            )
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname
        self._port = parsed.port
        self._transport = PooledHttpTransport(
            self._new_connection,
            max_connections=self.max_connections,
            acquire_timeout=45,
        )

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._scheme != "https":
            return None
        if not self.profile.verify_tls:
            return ssl._create_unverified_context()
        if self.profile.ca_file:
            return ssl.create_default_context(cafile=self.profile.ca_file)
        return ssl.create_default_context()

    def _headers(self, has_body: bool = False) -> dict[str, str]:
        token = self.profile.token()
        headers = {
            "Accept": "application/json",
            "User-Agent": "mcp-bridge-gitlab",
        }
        if self.profile.auth_type == "private_token":
            headers["PRIVATE-TOKEN"] = token
        elif self.profile.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["JOB-TOKEN"] = token
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _target(
        self,
        path: str,
        query: JsonObject | None = None,
    ) -> str:
        if not path.startswith("/"):
            raise GitLabError("GitLab API path must start with /")
        pairs: list[tuple[str, str]] = []
        for key, raw in (query or {}).items():
            if raw is None:
                continue
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                if isinstance(value, bool):
                    pairs.append((key, "true" if value else "false"))
                else:
                    pairs.append((key, str(value)))
        encoded = urllib.parse.urlencode(pairs, doseq=True)
        return "/api/v4" + path + (f"?{encoded}" if encoded else "")

    def _url(
        self,
        path: str,
        query: JsonObject | None = None,
    ) -> str:
        return self.profile.base_url.rstrip("/") + self._target(path, query)

    def _new_connection(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._hostname,
                self._port,
                timeout=45,
                context=self._ssl_context(),
            )
        return http.client.HTTPConnection(
            self._hostname,
            self._port,
            timeout=45,
        )

    def _error_message(self, status: int, target: str, data: JsonValue) -> str:
        detail = json.dumps(data, ensure_ascii=False)[:4096]
        if status == 401:
            return (
                f"GitLab authentication failed for profile {self.profile.profile_id!r} "
                f"(HTTP 401); check its {self.profile.auth_type} credential"
            )
        if status == 403:
            return (
                f"GitLab denied the operation for profile {self.profile.profile_id!r} "
                f"(HTTP 403); check token scopes, project membership, and role: {detail}"
            )
        if status == 429:
            return (
                f"GitLab rate limit exceeded for profile {self.profile.profile_id!r} "
                f"(HTTP 429) on {target}"
            )
        return f"GitLab API HTTP {status}: {detail}"

    @staticmethod
    def _decode_response(raw: bytes, headers: dict[str, str]) -> JsonValue:
        if not raw:
            return {}
        content_type = next(
            (
                value
                for key, value in headers.items()
                if key.casefold() == "content-type"
            ),
            "",
        )
        if "json" in content_type.casefold():
            try:
                return json_loads(raw, context="GitLab response")
            except ValueError as exc:
                raise GitLabError("GitLab returned invalid JSON") from exc
        return raw.decode("utf-8", "replace")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: JsonObject | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> GitLabResponse:
        body = (
            None
            if payload is None
            else json.dumps(
                json_value(payload, context="GitLab request payload"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        target = self._target(path, query)
        try:
            response = self._transport.request(
                method,
                target,
                body=body,
                headers=self._headers(has_body=body is not None),
            )
        except HttpTransportError as exc:
            raise GitLabError(
                f"GitLab API transport error for profile {self.profile.profile_id!r}: {exc}"
            ) from exc
        status, headers, raw = response.status, response.headers, response.body
        data = self._decode_response(raw, headers)
        if status >= 400 and not (allowed_errors and status in allowed_errors):
            raise GitLabError(self._error_message(status, target, data))
        return GitLabResponse(status=status, data=data, headers=headers)

    def request_text(self, method: str, path: str) -> GitLabResponse:
        target = self._target(path)
        try:
            response = self._transport.request(
                method,
                target,
                headers=self._headers(),
            )
        except HttpTransportError as exc:
            raise GitLabError(
                f"GitLab API transport error for profile {self.profile.profile_id!r}: {exc}"
            ) from exc
        status, headers, raw = response.status, response.headers, response.body
        text = raw.decode("utf-8", "replace")
        if status >= 400:
            raise GitLabError(self._error_message(status, target, text))
        return GitLabResponse(status=status, data=text, headers=headers)

    @staticmethod
    def project_selector(project: str | int) -> str:
        value = str(project).strip()
        if not value:
            raise GitLabError("project must be a numeric id or path_with_namespace")
        return urllib.parse.quote(value, safe="")
