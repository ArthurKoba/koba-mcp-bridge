from __future__ import annotations

from pydantic import Field

from common.models import StrictModel


class ManagementConfig(StrictModel):
    logging_enabled: bool = True
    logging_capture_payloads: bool = True
    logging_retention_days: int = Field(30, ge=1, le=3650)
    logging_max_records: int = Field(10_000, ge=100, le=1_000_000)
    file_auto_cleanup_enabled: bool = False
    file_retention_days: int = Field(30, ge=1, le=3650)
    file_cleanup_limit: int = Field(1_000, ge=1, le=10_000)
    maintenance_interval_minutes: int = Field(60, ge=1, le=1440)
