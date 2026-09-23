from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

from common.models import json_loads, json_object
from control_plane.domain.accounts import Account, AuthType, Provider


class ProviderConnectionVerifier:
    def verify(self, account: Account, credential: str) -> dict[str, object]:
        if account.provider is Provider.GITHUB:
            return self._verify_github(account, credential)
        return self._verify_gitlab(account, credential)

    @staticmethod
    def _verify_github(account: Account, private_key: str) -> dict[str, object]:
        if account.auth_type is not AuthType.GITHUB_APP:
            raise ValueError("unsupported GitHub auth type")
        if not account.external_id.isdigit():
            raise ValueError("GitHub App external_id must be numeric APP_ID")
        now = int(time.time())
        token = jwt.encode(
            {"iat": now - 60, "exp": now + 9 * 60, "iss": account.external_id},
            private_key.replace("\\n", "\n"),
            algorithm="RS256",
        )
        request = urllib.request.Request(
            account.base_url.rstrip("/") + "/app",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "mcp-bridge-control-plane",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2048].decode("utf-8", "replace")
            raise ValueError(f"GitHub verification failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"GitHub verification transport error: {exc.reason}") from exc
        data = json_object(json_loads(raw, context="GitHub app verification"))
        return {
            "ok": True,
            "provider": "github",
            "account": account.alias,
            "app_id": account.external_id,
            "slug": data.get("slug"),
            "name": data.get("name"),
        }

    @staticmethod
    def _verify_gitlab(account: Account, token: str) -> dict[str, object]:
        parsed = urllib.parse.urlsplit(account.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("GitLab base_url must be an http(s) origin")
        headers = {"Accept": "application/json", "User-Agent": "mcp-bridge-control-plane"}
        if account.auth_type is AuthType.PRIVATE_TOKEN:
            headers["PRIVATE-TOKEN"] = token
        elif account.auth_type is AuthType.BEARER:
            headers["Authorization"] = f"Bearer {token}"
        elif account.auth_type is AuthType.JOB_TOKEN:
            headers["JOB-TOKEN"] = token
        else:
            raise ValueError("unsupported GitLab auth type")

        context: ssl.SSLContext | None = None
        if parsed.scheme == "https":
            if not account.verify_tls:
                context = ssl._create_unverified_context()
            elif account.ca_cert_pem:
                context = ssl.create_default_context(
                    cadata=account.ca_cert_pem.replace("\\n", "\n")
                )
            else:
                context = ssl.create_default_context()
        request = urllib.request.Request(
            account.base_url.rstrip("/") + "/api/v4/user",
            method="GET",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15, context=context) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2048].decode("utf-8", "replace")
            raise ValueError(f"GitLab verification failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"GitLab verification transport error: {exc.reason}") from exc
        data = json_object(json_loads(raw, context="GitLab user verification"))
        return {
            "ok": True,
            "provider": "gitlab",
            "account": account.alias,
            "user_id": data.get("id"),
            "username": data.get("username"),
            "name": data.get("name"),
            "base_url": account.base_url,
        }
