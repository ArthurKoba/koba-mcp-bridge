from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .infisical_client import InfisicalClient
from .models import JsonObject
from .secret_errors import SecretError
from .secret_reference import SecretReference


class SecretResolver:
    def __init__(
        self,
        infisical: InfisicalClient | None = None,
        *,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        if infisical is None:
            raise ValueError("SecretResolver requires explicit InfisicalClient")
        self.infisical = infisical
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._secret_cache: dict[
            tuple[str, str, str, str],
            tuple[float, str],
        ] = {}
        self._inflight: dict[
            tuple[str, str, str, str],
            threading.Event,
        ] = {}
        self._cache_lock = threading.Lock()

    def _config_path(self, relative_path: str) -> str:
        base = self.infisical.config.base_path.strip("/")
        relative = relative_path.strip("/")
        parts = [part for part in (base, relative) if part]
        return "/" + "/".join(parts) if parts else "/"

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._secret_cache.clear()

    def _get_infisical_cached(
        self,
        secret_name: str,
        *,
        environment: str,
        secret_path: str,
        project_id: str = "",
    ) -> str:
        name = secret_name.strip()
        env = environment.strip()
        path = secret_path.strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        project = project_id.strip() or self.infisical.config.project_id
        key = (project, env, path, name)

        while True:
            now = time.monotonic()
            leader = False
            with self._cache_lock:
                cached = self._secret_cache.get(key)
                if cached is not None:
                    expires_at, value = cached
                    if expires_at > now:
                        return value
                    self._secret_cache.pop(key, None)

                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    leader = True

            if leader:
                break
            if not event.wait(timeout=30):
                raise SecretError(
                    "timed out waiting for concurrent Infisical secret fetch"
                )

        try:
            value, _metadata = self.infisical.get_secret(
                name,
                environment=env,
                secret_path=path,
                project_id=project,
            )
        except Exception:
            with self._cache_lock:
                event = self._inflight.pop(key, None)
                if event is not None:
                    event.set()
            raise

        with self._cache_lock:
            if self.cache_ttl_seconds > 0:
                self._secret_cache[key] = (
                    time.monotonic() + self.cache_ttl_seconds,
                    value,
                )
            event = self._inflight.pop(key, None)
            if event is not None:
                event.set()
        return value

    def get(self, relative_path: str, secret_name: str) -> str:
        return self._get_infisical_cached(
            secret_name,
            environment=self.infisical.config.environment,
            secret_path=self._config_path(relative_path),
        )

    def list_folders(self, relative_path: str) -> list[JsonObject]:
        return self.infisical.list_folders(
            environment=self.infisical.config.environment,
            secret_path=self._config_path(relative_path),
        )

    def resolve(self, reference: str) -> str:
        ref = SecretReference.parse(reference)
        if ref.scheme == "env":
            value = os.getenv(ref.env_name, "")
            if not value:
                raise SecretError(
                    f"environment secret {ref.env_name!r} is not configured"
                )
            return value

        if ref.scheme == "file":
            try:
                value = Path(ref.file_path).read_text(encoding="utf-8")
            except OSError as exc:
                raise SecretError("secret file cannot be read") from exc
            if not value:
                raise SecretError("secret file is empty")
            return value.rstrip("\r\n")

        return self._get_infisical_cached(
            ref.secret_name,
            environment=ref.environment,
            secret_path=ref.secret_path,
            project_id=ref.project_id,
        )

    def check(self, reference: str) -> JsonObject:
        ref = SecretReference.parse(reference)
        self.resolve(reference)
        return {
            "available": True,
            "reference": ref.public(),
        }
