from __future__ import annotations

import os
import threading
import time

from .gitlab_client import GitLabClient, GitLabProfileRegistry

_registry_lock = threading.Lock()


class _RegistryCacheState:
    def __init__(self) -> None:
        self.value: tuple[float, tuple[str, ...], GitLabProfileRegistry] | None = None


_registry_cache = _RegistryCacheState()
_client_cache: dict[str, GitLabClient] = {}


def _cache_ttl_seconds() -> float:
    raw = os.getenv("GITLAB_REGISTRY_CACHE_TTL_SECONDS", "60").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("GITLAB_REGISTRY_CACHE_TTL_SECONDS must be a number") from exc
    if value < 0 or value > 3600:
        raise RuntimeError(
            "GITLAB_REGISTRY_CACHE_TTL_SECONDS must be between 0 and 3600"
        )
    return value


def _registry_fingerprint() -> tuple[str, ...]:
    return (
        os.getenv("INFISICAL_HOST", ""),
        os.getenv("INFISICAL_PROJECT_ID", ""),
        os.getenv("INFISICAL_ENVIRONMENT", "prod"),
        os.getenv("INFISICAL_BASE_PATH", "/"),
        os.getenv("INFISICAL_CLIENT_ID", ""),
        os.getenv("INFISICAL_CLIENT_ID_FILE", ""),
        os.getenv("INFISICAL_CLIENT_SECRET_FILE", ""),
        os.getenv("INFISICAL_VERIFY_TLS", "true"),
        os.getenv("INFISICAL_CA_FILE", ""),
    )


def registry() -> GitLabProfileRegistry:
    ttl = _cache_ttl_seconds()
    fingerprint = _registry_fingerprint()
    now = time.monotonic()

    with _registry_lock:
        cached = _registry_cache.value
        if (
            ttl > 0
            and cached is not None
            and cached[0] > now
            and cached[1] == fingerprint
        ):
            return cached[2]

        value = GitLabProfileRegistry.from_infisical()
        _registry_cache.value = (now + ttl, fingerprint, value)
        return value


def client(profile_id: str) -> GitLabClient:
    profile = registry().get(profile_id)
    key = profile.profile_id.casefold()

    with _registry_lock:
        cached = _client_cache.get(key)
        if cached is not None and cached.profile == profile:
            return cached
        value = GitLabClient(profile)
        _client_cache[key] = value
        return value


def clear_runtime_cache() -> None:
    with _registry_lock:
        _registry_cache.value = None
        _client_cache.clear()
