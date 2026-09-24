from __future__ import annotations

import threading

from common.management_client import ManagementClient
from common.models import JsonObject
from common.settings import GitLabSettings

from .gitlab_client import GitLabClient
from .models import GitLabProfile


class GitLabRuntimeContext:
    def __init__(
        self,
        management: ManagementClient,
        settings: GitLabSettings,
    ) -> None:
        self.management = management
        self.settings = settings
        self._lock = threading.Lock()
        self._client_cache: dict[str, tuple[str, GitLabClient]] = {}

    def accounts(self) -> JsonObject:
        result = self.management.list_accounts(provider="gitlab").to_json()
        accounts = result.get("accounts")
        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                account["potential_capabilities"] = self._potential_capabilities(
                    str(account.get("auth_type", ""))
                )
                account["permission_scope"] = "project-dependent"
        return result

    @staticmethod
    def _potential_capabilities(auth_type: str) -> list[str]:
        capabilities = [
            "project_read",
            "repository_read",
            "repository_write",
            "issues",
            "merge_requests",
            "pipelines",
        ]
        if auth_type == "job_token":
            capabilities.append("job_token_scoped_access")
        elif auth_type == "private_token":
            capabilities.append("personal_access_token_scoped_access")
        else:
            capabilities.append("oauth_bearer_scoped_access")
        return capabilities

    def account_capabilities(
        self,
        account_id: str,
        project: str = "",
    ) -> JsonObject:
        client = self.client(account_id)
        result = client.account_capabilities(project.strip())
        result["potential_capabilities"] = self._potential_capabilities(
            client.profile.auth_type
        )
        result["permission_scope"] = "project-dependent"
        return result

    def client(self, account_id: str) -> GitLabClient:
        account = self.management.resolve_account(account_id, provider="gitlab")
        with self._lock:
            cached = self._client_cache.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            profile = GitLabProfile.model_validate(
                {
                    "account_id": account.id,
                    "alias": account.alias,
                    "base_url": account.base_url,
                    "auth_type": account.auth_type,
                    "verify_tls": account.verify_tls,
                    "ca_cert_pem": account.ca_cert_pem or "",
                }
            )
            profile.bind_token(account.credential)
            client = GitLabClient(
                profile,
                protected_branches=self.settings.protected_branches,
            )
            self._client_cache[account.id] = (account.updated_at, client)
            return client

    def clear(self) -> None:
        with self._lock:
            self._client_cache.clear()
