from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .account_contracts import AccountList, InvocationEvent, ResolvedAccount
from .models import JsonObject, json_loads, json_object
from .settings import ManagementClientSettings


class ManagementClientError(RuntimeError):
    pass


class ManagementClient:
    def __init__(self, settings: ManagementClientSettings) -> None:
        self.url = settings.url.rstrip("/")
        self.service_token = settings.service_token
        self.timeout_seconds = settings.timeout_seconds
        if not self.url:
            raise ValueError("CONTROL_PLANE_URL is required")

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: JsonObject | None = None,
        expect_body: bool = True,
    ) -> JsonObject:
        target = self.url + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.service_token}",
            "User-Agent": "mcp-bridge",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(target, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2048].decode("utf-8", "replace")
            raise ManagementClientError(
                f"management HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ManagementClientError(
                f"management transport error: {exc.reason}"
            ) from exc
        if not expect_body or not raw:
            return {}
        return json_object(
            json_loads(raw, context="management response"),
            context="management response",
        )

    def list_accounts(
        self,
        *,
        provider: str | None = None,
        role: str | None = None,
    ) -> AccountList:
        query: dict[str, str] = {}
        if provider:
            query["provider"] = provider
        if role:
            query["role"] = role
        data = self._request("GET", "/internal/accounts", query=query)
        return AccountList.model_validate(data)

    def resolve_account(
        self,
        selector: str,
        *,
        provider: str,
        role: str | None = None,
    ) -> ResolvedAccount:
        value = selector.strip()
        if not value:
            raise ValueError("account_id is required")
        query = {"provider": provider}
        if role:
            query["role"] = role
        path = "/internal/accounts/" + urllib.parse.quote(value, safe="") + "/resolve"
        data = self._request("GET", path, query=query)
        return ResolvedAccount.model_validate(data)

    def record_invocation(self, event: InvocationEvent) -> None:
        self._request(
            "POST",
            "/internal/events",
            payload=json_object(event.model_dump(mode="json"), context="invocation event"),
            expect_body=False,
        )
