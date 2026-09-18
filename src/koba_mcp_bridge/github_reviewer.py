from __future__ import annotations

import base64
import os
from functools import lru_cache

from .github_agent import GitHubAgentError
from .github_identity import GitHubPrettyIdentityClient
from .secrets import (
    InfisicalConfig,
    SecretError,
    resolve_config_secret,
    resolve_secret,
)


def github_reviewer_configured() -> bool:
    if InfisicalConfig.from_env().configured():
        return True
    return bool(
        os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
        and (
            os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_REF", "").strip()
            or os.getenv("GITHUB_REVIEWER_PRIVATE_KEY", "").strip()
            or os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_B64", "").strip()
        )
    )


def _reviewer_app_id() -> str:
    try:
        return resolve_config_secret("github/reviewer", "APP_ID").strip()
    except SecretError:
        app_id = os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
        if app_id:
            return app_id
        raise GitHubAgentError("GitHub reviewer APP_ID is not configured")


def _reviewer_private_key_from_env() -> str:
    try:
        return resolve_config_secret(
            "github/reviewer",
            "PRIVATE_KEY_PEM",
        ).replace("\\n", "\n")
    except SecretError:
        pass

    secret_ref = os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_REF", "").strip()
    raw = os.getenv("GITHUB_REVIEWER_PRIVATE_KEY", "").strip()
    encoded = os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_B64", "").strip()

    if secret_ref:
        try:
            return resolve_secret(secret_ref).replace("\\n", "\n")
        except SecretError:
            if not raw and not encoded:
                raise

    if raw:
        return raw.replace("\\n", "\n")

    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:  # pragma: no cover - defensive configuration path
            raise GitHubAgentError(
                "GITHUB_REVIEWER_PRIVATE_KEY_B64 is not valid base64 UTF-8"
            ) from exc

    raise GitHubAgentError("GitHub reviewer private key is not configured")

@lru_cache(maxsize=1)
def github_reviewer_client_from_env() -> GitHubPrettyIdentityClient:
    return GitHubPrettyIdentityClient(
        app_id=_reviewer_app_id(),
        private_key=_reviewer_private_key_from_env(),
    )
