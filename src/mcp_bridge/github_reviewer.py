from __future__ import annotations

from functools import lru_cache

from .github_agent import GitHubAgentError
from .github_identity import GitHubPrettyIdentityClient
from .secrets import SecretError, resolve_config_secret


def github_reviewer_configured() -> bool:
    try:
        return bool(
            resolve_config_secret("github/reviewer", "APP_ID").strip()
            and resolve_config_secret(
                "github/reviewer",
                "PRIVATE_KEY_PEM",
            ).strip()
        )
    except SecretError:
        return False


def _reviewer_app_id() -> str:
    try:
        value = resolve_config_secret("github/reviewer", "APP_ID").strip()
    except SecretError as exc:
        raise GitHubAgentError(
            f"unable to load GitHub reviewer APP_ID from Infisical: {exc}"
        ) from exc
    if not value:
        raise GitHubAgentError("GitHub reviewer APP_ID is empty")
    return value


def _reviewer_private_key() -> str:
    try:
        value = resolve_config_secret(
            "github/reviewer",
            "PRIVATE_KEY_PEM",
        ).replace("\\n", "\n").strip()
    except SecretError as exc:
        raise GitHubAgentError(
            "unable to load GitHub reviewer PRIVATE_KEY_PEM from Infisical: "
            f"{exc}"
        ) from exc
    if not value:
        raise GitHubAgentError("GitHub reviewer PRIVATE_KEY_PEM is empty")
    return value


@lru_cache(maxsize=1)
def github_reviewer_client() -> GitHubPrettyIdentityClient:
    return GitHubPrettyIdentityClient(
        app_id=_reviewer_app_id(),
        private_key=_reviewer_private_key(),
    )
