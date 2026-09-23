from __future__ import annotations

from .infisical_client import InfisicalClient
from .models import JsonObject
from .secret_config import InfisicalConfig, _env_float
from .secret_errors import SecretError
from .secret_reference import SecretReference
from .secret_resolver import SecretResolver

__all__ = [
    "InfisicalClient",
    "InfisicalConfig",
    "SecretError",
    "SecretReference",
    "SecretResolver",
    "list_config_folders",
    "resolve_config_secret",
    "resolve_secret",
    "secret_reference_available",
    "secrets_status",
]


_default_resolver = SecretResolver(
    cache_ttl_seconds=_env_float(
        "INFISICAL_CACHE_TTL_SECONDS",
        60.0,
        minimum=0.0,
        maximum=3600.0,
    )
)


def resolve_secret(reference: str) -> str:
    """Resolve an explicit secret reference for internal connector use."""
    return _default_resolver.resolve(reference)


def resolve_config_secret(relative_path: str, secret_name: str) -> str:
    """Resolve one convention-based Infisical secret under the configured base path."""
    return _default_resolver.get(relative_path, secret_name)


def list_config_folders(relative_path: str) -> list[JsonObject]:
    """List immediate Infisical folders under one convention-based path."""
    return _default_resolver.list_folders(relative_path)


def secret_reference_available(reference: str) -> JsonObject:
    return _default_resolver.check(reference)


def secrets_status(authenticate: bool = False) -> JsonObject:
    return _default_resolver.infisical.status(authenticate=authenticate)
