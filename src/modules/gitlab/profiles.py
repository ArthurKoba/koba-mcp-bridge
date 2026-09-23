from __future__ import annotations

import re
import urllib.parse

from common.models import JsonObject

from . import credentials
from .errors import GitLabError
from .models import GitLabProfile, GitLabProfileListResponse, GitLabProfilePublic

_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_AUTH = {"private_token", "bearer", "job_token"}


class GitLabProfileRegistry:
    def __init__(self, profiles: dict[str, GitLabProfile]) -> None:
        self._profiles = profiles

    @staticmethod
    def _optional_secret(path: str, name: str, default: str = "") -> str:
        try:
            return credentials.resolve_config_secret(path, name).strip()
        except credentials.SecretError:
            return default

    @classmethod
    def _from_infisical(cls) -> list[GitLabProfile]:
        try:
            folders = credentials.list_config_folders("gitlab/accounts")
        except credentials.SecretError as exc:
            raise GitLabError(
                f"unable to discover GitLab profiles from Infisical: {exc}"
            ) from exc

        profiles: list[GitLabProfile] = []
        for folder in folders:
            profile_id = str(folder.get("name", "")).strip()
            if not _PROFILE_ID_RE.fullmatch(profile_id):
                continue
            path = f"gitlab/accounts/{profile_id}"
            try:
                base_url = credentials.resolve_config_secret(path, "BASE_URL").strip().rstrip("/")
            except credentials.SecretError as exc:
                raise GitLabError(
                    f"GitLab profile {profile_id!r} is missing/unreadable BASE_URL: {exc}"
                ) from exc

            auth_type = cls._optional_secret(
                path,
                "AUTH_TYPE",
                "private_token",
            ).casefold()
            if auth_type not in _ALLOWED_AUTH:
                raise GitLabError(
                    f"profile {profile_id!r} AUTH_TYPE must be one of "
                    f"{sorted(_ALLOWED_AUTH)}"
                )
            parsed = urllib.parse.urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise GitLabError(
                    f"profile {profile_id!r} has invalid BASE_URL"
                )

            verify_raw = cls._optional_secret(path, "VERIFY_TLS", "true")
            verify_tls = verify_raw.casefold() not in {"0", "false", "no", "off"}
            profile = GitLabProfile.model_validate(
                    {
                        "profile_id": profile_id,
                        "base_url": base_url,
                        "auth_type": auth_type,
                        "convention_path": path,
                        "verify_tls": verify_tls,
                        "ca_file": cls._optional_secret(path, "CA_FILE"),
                        "label": cls._optional_secret(path, "LABEL", profile_id),
                    }
                )
            profile.bind_token_resolver(credentials.resolve_config_secret)
            profiles.append(profile)
        return profiles

    @classmethod
    def from_infisical(cls) -> GitLabProfileRegistry:
        profiles = {
            profile.profile_id.casefold(): profile
            for profile in cls._from_infisical()
        }
        return cls(profiles)

    def list(self) -> JsonObject:
        profiles = sorted(
            (
                GitLabProfilePublic.model_validate(profile.public())
                for profile in self._profiles.values()
            ),
            key=lambda item: item.profile_id.casefold(),
        )
        return GitLabProfileListResponse(
            profiles=profiles,
            count=len(profiles),
        ).to_json()

    def get(self, profile_id: str) -> GitLabProfile:
        key = profile_id.strip().casefold()
        profile = self._profiles.get(key)
        if profile is None:
            raise GitLabError(f"unknown GitLab profile_id: {profile_id}")
        return profile
