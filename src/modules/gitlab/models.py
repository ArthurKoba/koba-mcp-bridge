from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator

from common.models import JsonObject, JsonValue, StrictModel


def _unbound_token_resolver(_path: str, _name: str) -> str:
    raise RuntimeError("GitLab token resolver is not bound")


class GitLabProfile(StrictModel):
    _token_resolver: Callable[[str, str], str] = PrivateAttr(
        default_factory=lambda: _unbound_token_resolver
    )

    profile_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    base_url: str = Field(min_length=1)
    auth_type: Literal["private_token", "bearer", "job_token"]
    convention_path: str = Field(min_length=1)
    verify_tls: bool = True
    ca_file: str = ""
    label: str = ""

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def api_url(self) -> str:
        return self.base_url + "/api/v4"

    def bind_token_resolver(
        self,
        resolver: Callable[[str, str], str],
    ) -> None:
        self._token_resolver = resolver

    def token(self) -> str:
        return self._token_resolver(self.convention_path, "TOKEN")

    def public(self) -> JsonObject:
        return GitLabProfilePublic(
            profile_id=self.profile_id,
            label=self.label,
            base_url=self.base_url,
            api_url=self.api_url,
            auth_type=self.auth_type,
            credential_source={
                "type": "infisical_convention",
                "path": self.convention_path,
                "secret": "TOKEN",
            },
            credential_configured=True,
            verify_tls=self.verify_tls,
            ca_file=self.ca_file or None,
        ).to_json()


class GitLabProfilePublic(StrictModel):
    profile_id: str
    label: str
    base_url: str
    api_url: str
    auth_type: str
    credential_source: JsonObject
    credential_configured: bool
    verify_tls: bool
    ca_file: str | None


class GitLabProfileListResponse(StrictModel):
    profiles: list[GitLabProfilePublic]
    count: int = Field(ge=0)


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
