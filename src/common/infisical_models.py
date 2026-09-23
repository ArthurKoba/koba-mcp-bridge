from __future__ import annotations

from pydantic import Field

from .models import ProviderModel


class InfisicalAuthResponse(ProviderModel):
    access_token: str = Field(alias="accessToken", min_length=1)
    expires_in: float = Field(alias="expiresIn", gt=0)


class InfisicalFolder(ProviderModel):
    name: str = Field(min_length=1)


class InfisicalFolderResponse(ProviderModel):
    folders: list[InfisicalFolder]


class InfisicalSecret(ProviderModel):
    secret_value: str = Field(alias="secretValue")
    id: str | int | None = None
    secret_key: str | None = Field(default=None, alias="secretKey")
    secret_path: str | None = Field(default=None, alias="secretPath")
    version: str | int | None = None
    updated_at: str | None = Field(default=None, alias="updatedAt")


class InfisicalSecretResponse(ProviderModel):
    secret: InfisicalSecret
