from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field

from common.models import StrictModel


class Invocation(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[0-9a-f-]{36}$")
    request_id: str = ""
    module: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=256)
    account_id: str = ""
    provider: str = ""
    status: Literal["success", "error"]
    duration_ms: float = Field(ge=0)
    error_type: str = ""
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
