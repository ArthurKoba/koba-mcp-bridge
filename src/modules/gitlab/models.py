from __future__ import annotations

from typing import Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator

from common.models import JsonObject, JsonValue, StrictModel


class GitLabProfile(StrictModel):
    _token: str = PrivateAttr(default="")

    account_id: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    auth_type: Literal["private_token", "bearer", "job_token"]
    verify_tls: bool = True
    ca_cert_pem: str = ""
    label: str = ""

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def profile_id(self) -> str:
        return self.account_id

    @property
    def api_url(self) -> str:
        return self.base_url + "/api/v4"

    def bind_token(self, token: str) -> None:
        value = token.strip()
        if not value:
            raise ValueError("GitLab credential is empty")
        self._token = value

    def token(self) -> str:
        if not self._token:
            raise RuntimeError("GitLab credential is not bound")
        return self._token

    def public(self) -> JsonObject:
        return {
            "account_id": self.account_id,
            "alias": self.alias,
            "label": self.label,
            "base_url": self.base_url,
            "api_url": self.api_url,
            "auth_type": self.auth_type,
            "credential_configured": bool(self._token),
            "verify_tls": self.verify_tls,
            "ca_cert_pem_configured": bool(self.ca_cert_pem),
        }


class GitLabResponse(StrictModel):
    status: int = Field(ge=100, le=599)
    data: JsonValue
    headers: dict[str, str]


class GitLabCommitAction(StrictModel):
    action: Literal["create", "update", "delete", "move", "chmod"]
    file_path: str = Field(min_length=1)
    content: str | None = None
    previous_path: str | None = None
    encoding: Literal["text", "base64"] | None = None
    execute_filemode: bool | None = None
    last_commit_id: str | None = None

    @model_validator(mode="after")
    def validate_action(self) -> GitLabCommitAction:
        if self.action in {"create", "update"} and self.content is None:
            raise ValueError(f"{self.action} actions require content")
        if self.action == "move" and not self.previous_path:
            raise ValueError("move actions require previous_path")
        return self
