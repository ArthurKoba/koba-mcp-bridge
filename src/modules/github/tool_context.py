from __future__ import annotations

import threading

from common.management_client import ManagementClient
from common.models import JsonObject
from common.settings import GitHubPolicySettings

from .github_identity import GitHubPrettyIdentityClient


class GitHubRuntimeContext:
    def __init__(
        self,
        management: ManagementClient,
        policy: GitHubPolicySettings,
    ) -> None:
        self.management = management
        self.policy = policy
        self._lock = threading.Lock()
        self._clients: dict[
            tuple[str, str],
            tuple[str, GitHubPrettyIdentityClient],
        ] = {}

    def list_accounts(self) -> JsonObject:
        result = self.management.list_accounts(provider="github").to_json()
        accounts = result.get("accounts")
        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                auth_type = str(account.get("auth_type", ""))
                account["potential_capabilities"] = self._potential_capabilities(auth_type)
                account["permission_scope"] = "repository-dependent"
        return result

    @staticmethod
    def _potential_capabilities(auth_type: str) -> list[str]:
        capabilities = [
            "repository_read",
            "repository_write",
            "issues",
            "pull_requests",
            "reviews",
            "actions",
            "checks",
            "git_history",
        ]
        if auth_type == "github_app":
            capabilities.append("installation_scoped_access")
        else:
            capabilities.append("user_token_scoped_access")
        return capabilities

    def account_capabilities(
        self,
        account_id: str,
        repository: str = "",
    ) -> JsonObject:
        client = self._client(account_id)
        result = client.account_capabilities()
        result["potential_capabilities"] = self._potential_capabilities(client.auth_type)
        result["permission_scope"] = "repository-dependent"
        if repository.strip():
            result["repository"] = client.capabilities(repository.strip())
        return result

    def _client(self, account_id: str) -> GitHubPrettyIdentityClient:
        account = self.management.resolve_account(account_id, provider="github")
        key = ("github", account.id)
        with self._lock:
            cached = self._clients.get(key)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = GitHubPrettyIdentityClient.from_account(account, self.policy)
            self._clients[key] = (account.updated_at, client)
            return client

    def client(self, account_id: str) -> GitHubPrettyIdentityClient:
        return self._client(account_id)

    def clear(self) -> None:
        with self._lock:
            self._clients.clear()
