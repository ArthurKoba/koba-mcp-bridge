from __future__ import annotations

from .infisical_client import InfisicalClient
from .models import JsonObject
from .secret_config import InfisicalConfig
from .secret_errors import SecretError
from .secret_reference import SecretReference
from .secret_resolver import SecretResolver

__all__ = [
    "InfisicalClient",
    "InfisicalConfig",
    "SecretError",
    "SecretReference",
    "SecretResolver",
    "configure_secrets",
    "list_config_folders",
    "resolve_config_secret",
    "resolve_secret",
    "secret_reference_available",
    "secrets_status",
]

class _SecretRuntime:
    def __init__(self) -> None:
        self.resolver: SecretResolver | None = None


_runtime = _SecretRuntime()


def configure_secrets(config: InfisicalConfig, *, cache_ttl_seconds: float = 60.0) -> None:
    _runtime.resolver = SecretResolver(
        InfisicalClient(config),
        cache_ttl_seconds=cache_ttl_seconds,
    )


def _resolver() -> SecretResolver:
    if _runtime.resolver is None:
        raise SecretError("secret service is not configured by the application bootstrap")
    return _runtime.resolver


def resolve_secret(reference: str) -> str:
    """Resolve an explicit secret reference for internal connector use."""
    return _resolver().resolve(reference)


def resolve_config_secret(relative_path: str, secret_name: str) -> str:
    """Resolve one convention-based Infisical secret under the configured base path."""
    return _resolver().get(relative_path, secret_name)


def list_config_folders(relative_path: str) -> list[JsonObject]:
    """List immediate Infisical folders under one convention-based path."""
    return _resolver().list_folders(relative_path)


def secret_reference_available(reference: str) -> JsonObject:
    return _resolver().check(reference)


def secrets_status(authenticate: bool = False) -> JsonObject:
    return _resolver().infisical.status(authenticate=authenticate)
