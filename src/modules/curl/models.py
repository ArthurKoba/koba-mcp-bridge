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


class CurlRequestResponse(StrictModel):
    status: int = Field(ge=0, le=999)
    ok: bool
    final_url: str
    redirect_count: int = Field(ge=0)
    response_chain: list[HeaderBlock]
    response_headers: list[HeaderField]
    set_cookies: list[str]
    content_type: str
    body_size_bytes: int = Field(ge=0)
    body_truncated: bool
    curl_exit_code: int
    curl_error: str
    redirect_follow_blocked_sensitive: bool
    timings: JsonObject
    network: JsonObject
    request: JsonObject
    error: CurlDiagnostic | None = None
    body_is_text: bool
    body_encoding: str | None = None
    body_preview_text: str | None = None
    body_preview_hex: str | None = None
    body_text: str | None = None


class CurlDownloadResponse(StrictModel):
    status: int = Field(ge=0, le=999)
    ok: bool
    final_url: str
    redirect_count: int = Field(ge=0)
    response_chain: list[HeaderBlock]
    response_headers: list[HeaderField]
    set_cookies: list[str]
    content_type: str
    file: FileInfo
    curl_exit_code: int
    curl_error: str
    body_is_text: bool
    body_encoding: str | None = None
    body_preview_text: str | None = None
    body_preview_hex: str | None = None


class CurlStreamResponse(StrictModel):
    status: int = Field(ge=0, le=999)
    final_url: str
    stop_reason: str
    elapsed_seconds: float = Field(ge=0)
    captured_bytes: int = Field(ge=0)
    max_bytes: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    response_chain: list[HeaderBlock]
    response_headers: list[HeaderField]
    set_cookies: list[str]
    content_type: str
    file: FileInfo
    curl_exit_code: int
    curl_error: str
    error: CurlDiagnostic | None = None
    redirect_follow_blocked_sensitive: bool
    body_is_text: bool
    body_encoding: str | None = None
    body_preview_text: str | None = None
    body_preview_hex: str | None = None
