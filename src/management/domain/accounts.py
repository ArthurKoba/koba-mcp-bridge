from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from common.models import JsonObject, StrictModel


class Provider(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"


class AccountRole(StrEnum):
    DEVELOPMENT = "development"
    REVIEWER = "reviewer"
    GENERAL = "general"


class AuthType(StrEnum):
    GITHUB_APP = "github_app"
    PRIVATE_TOKEN = "private_token"
    BEARER = "bearer"
    JOB_TOKEN = "job_token"


class Account(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[0-9a-f-]{36}$")
    alias: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    provider: Provider
    role: AccountRole = AccountRole.GENERAL
    auth_type: AuthType
    label: str = Field(default="", max_length=256)
    base_url: str = Field(default="", max_length=2048)
    external_id: str = Field(default="", max_length=512)
    verify_tls: bool = True
    ca_cert_pem: str = Field(default="", max_length=65536)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("alias", mode="before")
    @classmethod
    def _normalize_alias(cls, value: str) -> str:
        return value.strip().casefold()

    @field_validator("label", "base_url", "external_id", "ca_cert_pem")
    @classmethod
    def _strip_strings(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _validate_provider_contract(self) -> Account:
        if self.provider is Provider.GITHUB:
            if self.auth_type is not AuthType.GITHUB_APP:
                raise ValueError("GitHub accounts currently require auth_type=github_app")
            if self.role not in {AccountRole.DEVELOPMENT, AccountRole.REVIEWER}:
                raise ValueError("GitHub accounts require development or reviewer role")
            if not self.external_id:
                raise ValueError("GitHub App accounts require external_id=APP_ID")
            base_url = self.base_url or "https://api.github.com"
            if base_url.rstrip("/") != "https://api.github.com":
                raise ValueError("custom GitHub API base URLs are not supported yet")
            object.__setattr__(self, "base_url", "https://api.github.com")
        else:
            if self.role is not AccountRole.GENERAL:
                raise ValueError("GitLab accounts use role=general")
            if self.auth_type not in {
                AuthType.PRIVATE_TOKEN,
                AuthType.BEARER,
                AuthType.JOB_TOKEN,
            }:
                raise ValueError("GitLab account auth_type must be token based")
            base_url = (self.base_url or "https://gitlab.com").rstrip("/")
            parsed = urllib.parse.urlsplit(base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("GitLab base_url must be an http(s) URL without credentials/query")
            object.__setattr__(self, "base_url", base_url)
        return self

    def public(self) -> JsonObject:
        return {
            "id": str(self.id),
            "alias": self.alias,
            "provider": self.provider.value,
            "role": self.role.value,
            "auth_type": self.auth_type.value,
            "label": self.label,
            "base_url": self.base_url,
            "external_id": self.external_id or None,
            "verify_tls": self.verify_tls,
            "ca_cert_pem": self.ca_cert_pem or None,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
