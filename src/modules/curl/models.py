from __future__ import annotations

from pydantic import Field, model_validator

from common.models import JsonObject, StrictModel
from modules.files.models import FileInfo


class CurlPresetDefinition(StrictModel):
    description: str
    headers: dict[str, str]


class CurlPreset(StrictModel):
    name: str
    description: str
    headers: dict[str, str]


class CurlPresetsResponse(StrictModel):
    default_preset: str
    presets: list[CurlPreset]


class HeaderField(StrictModel):
    name: str
    value: str


class HeaderBlock(StrictModel):
    status_line: str
    status: int = Field(ge=0, le=999)
    headers: list[HeaderField]


class CurlDiagnostic(StrictModel):
    error_type: str
    error_hint: str
    error_detail: str | None = None


class BodyPreview(StrictModel):
    body_is_text: bool
    body_encoding: str | None = None
    body_preview_text: str | None = None
    body_preview_hex: str | None = None
    body_text: str | None = None

    @model_validator(mode="after")
    def validate_preview_shape(self) -> BodyPreview:
        if self.body_is_text and self.body_preview_hex is not None:
            raise ValueError("text preview cannot include body_preview_hex")
        if not self.body_is_text and (
            self.body_encoding is not None
            or self.body_preview_text is not None
            or self.body_text is not None
        ):
            raise ValueError("binary preview cannot include text fields")
        return self

