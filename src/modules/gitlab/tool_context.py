from __future__ import annotations

import threading

from common.account_client import ControlPlaneClient
from common.models import JsonObject
from common.settings import GitLabSettings

from .gitlab_client import GitLabClient
from .models import GitLabProfile


class GitLabRuntimeContext:
    def __init__(
        self,
        control_plane: ControlPlaneClient,
        settings: GitLabSettings,
    ) -> None:
        self.control_plane = control_plane
        self.settings = settings
        self._lock = threading.Lock()
        self._client_cache: dict[str, tuple[str, GitLabClient]] = {}

    def accounts(self) -> JsonObject:
        return self.control_plane.list_accounts(provider="gitlab").to_json()

    def client(self, account_id: str) -> GitLabClient:
        account = self.control_plane.resolve_account(account_id, provider="gitlab")
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
                    "label": account.label or account.alias,
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
