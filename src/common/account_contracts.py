from __future__ import annotations

from typing import Literal

from pydantic import Field

from .models import JsonObject, StrictModel


class AccountPublic(StrictModel):
    id: str
    alias: str
    provider: Literal["github", "gitlab"]
    auth_type: str
    base_url: str
    external_id: str | None = None
    verify_tls: bool = True
    ca_cert_pem: str | None = None
    enabled: bool = True
    created_at: str
    updated_at: str


class ResolvedAccount(AccountPublic):
    credential: str = Field(min_length=1)


class AccountList(StrictModel):
    accounts: list[AccountPublic]
    count: int = Field(ge=0)

    def to_json(self) -> JsonObject:
        return self.model_dump(mode="json")


class InvocationEvent(StrictModel):
    request_id: str = ""
    module: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=256)
    account_id: str = ""
    provider: str = ""
    status: Literal["success", "error"]
    duration_ms: float = Field(ge=0)
    error_type: str = ""
    arguments_json: str = ""
    result_json: str = ""
    error_message: str = ""
