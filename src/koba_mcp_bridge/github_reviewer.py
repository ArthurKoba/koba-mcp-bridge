from __future__ import annotations

import base64
import os
from functools import lru_cache

from .github_agent import GitHubAgentError
from .github_collab import GitHubCollabClient


def github_reviewer_configured() -> bool:
    return bool(
        os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
        and (
            os.getenv("GITHUB_REVIEWER_PRIVATE_KEY", "").strip()
            or os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_B64", "").strip()
        )
        and os.getenv("GITHUB_REVIEWER_ALLOWED_REPOSITORIES", "").strip()
    )


def _reviewer_private_key_from_env() -> str:
    raw = os.getenv("GITHUB_REVIEWER_PRIVATE_KEY", "").strip()
    if raw:
        return raw.replace("\\n", "\n")

    encoded = os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:  # pragma: no cover - defensive configuration path
            raise GitHubAgentError(
                "GITHUB_REVIEWER_PRIVATE_KEY_B64 is not valid base64 UTF-8"
            ) from exc

    raise GitHubAgentError("GitHub reviewer private key is not configured")


def _reviewer_allowed_repositories_from_env() -> set[str]:
    raw = os.getenv("GITHUB_REVIEWER_ALLOWED_REPOSITORIES", "")
    repositories = {item.strip().casefold() for item in raw.split(",") if item.strip()}
    if not repositories:
        raise GitHubAgentError("GITHUB_REVIEWER_ALLOWED_REPOSITORIES is empty")
    if "*" in repositories:
        raise GitHubAgentError("wildcard reviewer repository access is intentionally unsupported")
    return repositories


@lru_cache(maxsize=1)
def github_reviewer_client_from_env() -> GitHubCollabClient:
    app_id = os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
    if not app_id:
        raise GitHubAgentError("GITHUB_REVIEWER_APP_ID is not configured")
    return GitHubCollabClient(
        app_id=app_id,
        private_key=_reviewer_private_key_from_env(),
        allowed_repositories=_reviewer_allowed_repositories_from_env(),
    )
