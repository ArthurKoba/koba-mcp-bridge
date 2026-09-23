from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from common.models import StrictModel


class ReviewComment(StrictModel):
    model_config = ConfigDict(
        extra="ignore",
        strict=True,
        validate_assignment=True,
    )

    path: str = Field(min_length=1)
    body: str = Field(min_length=1)
    line: int | None = Field(default=None, gt=0)
    side: Literal["LEFT", "RIGHT"] | None = None
    start_line: int | None = Field(default=None, gt=0)
    start_side: Literal["LEFT", "RIGHT"] | None = None
    position: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> ReviewComment:
        if self.start_line is not None and self.line is None:
            raise ValueError("start_line requires line")
        if self.start_side is not None and self.start_line is None:
            raise ValueError("start_side requires start_line")
        return self


class CopySpec(StrictModel):
    source_path: str = Field(min_length=1)
    destination_path: str = Field(min_length=1)
    mode: str | None = None


class AtomicChange(StrictModel):
    path: str = Field(min_length=1)
    operation: Literal["upsert", "create", "update", "delete", "copy"] = "upsert"
    mode: str = "100644"
    content: str | None = None
    content_base64: str | None = None
    source_path: str | None = None
    source_ref: str | None = None

    @model_validator(mode="after")
    def validate_operation_fields(self) -> AtomicChange:
        if self.operation == "delete":
            if any(
                value is not None
                for value in (
                    self.content,
                    self.content_base64,
                    self.source_path,
                    self.source_ref,
                )
            ):
                raise ValueError("delete changes cannot include content or copy fields")
            return self

        if self.operation == "copy":
            if not self.source_path or not self.source_ref:
                raise ValueError("copy changes require source_path and source_ref")
            if self.content is not None or self.content_base64 is not None:
                raise ValueError("copy changes cannot include content")
            return self

        if (self.content is None) == (self.content_base64 is None):
            raise ValueError(
                "create/update/upsert changes require exactly one of content or content_base64"
            )
        if self.source_path is not None or self.source_ref is not None:
            raise ValueError("create/update/upsert changes cannot include copy fields")
        return self
