from __future__ import annotations

import threading

from common.account_client import ControlPlaneClient
from common.models import JsonObject
from common.settings import GitHubPolicySettings

from .github_identity import GitHubPrettyIdentityClient


class GitHubRuntimeContext:
    def __init__(
        self,
        control_plane: ControlPlaneClient,
        policy: GitHubPolicySettings,
    ) -> None:
        self.control_plane = control_plane
        self.policy = policy
        self._lock = threading.Lock()
        self._clients: dict[
            tuple[str, str],
            tuple[str, GitHubPrettyIdentityClient],
        ] = {}

    def list_accounts(self, role: str | None = None) -> JsonObject:
        return self.control_plane.list_accounts(provider="github", role=role).to_json()

    def _client(self, account_id: str, role: str) -> GitHubPrettyIdentityClient:
        account = self.control_plane.resolve_account(
            account_id,
            provider="github",
            role=role,
        )
        key = (role, account.id)
        with self._lock:
            cached = self._clients.get(key)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = GitHubPrettyIdentityClient.from_account(account, self.policy)
            self._clients[key] = (account.updated_at, client)
            return client

    def development_client(self, account_id: str) -> GitHubPrettyIdentityClient:
        return self._client(account_id, "development")

    def reviewer_client(self, account_id: str) -> GitHubPrettyIdentityClient:
        return self._client(account_id, "reviewer")

    def reviewer_available(self) -> bool:
        return self.control_plane.list_accounts(provider="github", role="reviewer").count > 0

    def clear(self) -> None:
        with self._lock:
            self._clients.clear()
