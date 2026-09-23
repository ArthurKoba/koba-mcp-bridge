from __future__ import annotations

import threading
import time

from common.settings import GitLabSettings

from .gitlab_client import GitLabClient, GitLabProfileRegistry


class GitLabRuntimeContext:
    def __init__(self, settings: GitLabSettings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._registry_cache: tuple[float, GitLabProfileRegistry] | None = None
        self._client_cache: dict[str, GitLabClient] = {}

    def registry(self) -> GitLabProfileRegistry:
        ttl = self.settings.registry_cache_ttl_seconds
        now = time.monotonic()
        with self._lock:
            cached = self._registry_cache
            if ttl > 0 and cached is not None and cached[0] > now:
                return cached[1]
            value = GitLabProfileRegistry.from_infisical()
            self._registry_cache = (now + ttl, value)
            return value

    def client(self, profile_id: str) -> GitLabClient:
        profile = self.registry().get(profile_id)
        key = profile.profile_id.casefold()
        with self._lock:
            cached = self._client_cache.get(key)
            if cached is not None and cached.profile == profile:
                return cached
            value = GitLabClient(
                profile,
                protected_branches=self.settings.protected_branches,
            )
            self._client_cache[key] = value
            return value

    def clear(self) -> None:
        with self._lock:
            self._registry_cache = None
            self._client_cache.clear()


class _RuntimeHolder:
    def __init__(self) -> None:
        self.context: GitLabRuntimeContext | None = None


_runtime = _RuntimeHolder()


def configure_runtime(settings: GitLabSettings) -> GitLabRuntimeContext:
    _runtime.context = GitLabRuntimeContext(settings)
    return _runtime.context


def _context() -> GitLabRuntimeContext:
    if _runtime.context is None:
        raise RuntimeError("GitLab runtime is not configured by the application bootstrap")
    return _runtime.context


def registry() -> GitLabProfileRegistry:
    return _context().registry()


def client(profile_id: str) -> GitLabClient:
    return _context().client(profile_id)


def clear_runtime_cache() -> None:
    if _runtime.context is not None:
        _runtime.context.clear()
