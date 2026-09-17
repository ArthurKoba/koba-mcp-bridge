from __future__ import annotations

import base64
import os
from functools import lru_cache

from .github_agent import GitHubAgentError
from .github_identity import GitHubPrettyIdentityClient


def github_reviewer_configured() -> bool:
    return bool(
        os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
        and (
            os.getenv("GITHUB_REVIEWER_PRIVATE_KEY", "").strip()
            or os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_B64", "").strip()
        )
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


@lru_cache(maxsize=1)
def github_reviewer_client_from_env() -> GitHubPrettyIdentityClient:
    app_id = os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
    if not app_id:
        raise GitHubAgentError("GITHUB_REVIEWER_APP_ID is not configured")
    return GitHubPrettyIdentityClient(
        app_id=app_id,
        private_key=_reviewer_private_key_from_env(),
    )
