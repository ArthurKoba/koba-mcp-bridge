from __future__ import annotations

from pydantic import Field

from common.models import ProviderModel


class BackendStatus(ProviderModel):
    success: bool | None = None
    error: str | None = None


class StageBeginResponse(BackendStatus):
    stage_id: str = Field(min_length=1)
    chunk_bytes: int = Field(gt=0, le=8 * 1024 * 1024)


class StageWriteResponse(BackendStatus):
    next_offset: int = Field(ge=0)


class StageFinishResponse(BackendStatus):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class ProjectInfo(BackendStatus):
    has_project: bool
    project_name: str = Field(min_length=1)
