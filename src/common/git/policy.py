from __future__ import annotations

from typing import Self

from pydantic import field_validator

from common.models import StrictModel


class ProtectedBranchError(ValueError):
    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__(f"direct mutation of protected branch is disabled: {branch}")


class ProtectedBranchPolicy(StrictModel):
    protected: frozenset[str]

    @field_validator("protected", mode="before")
    @classmethod
    def normalize_branches(cls, value: object) -> frozenset[str]:
        if isinstance(value, str):
            return frozenset(
                item.strip().casefold()
                for item in value.split(",")
                if item.strip()
            )
        if isinstance(value, (set, frozenset, list, tuple)):
            return frozenset(
                str(item).strip().casefold()
                for item in value
                if str(item).strip()
            )
        raise ValueError("protected branches must be a string or collection")

    @classmethod
    def from_value(cls, value: object) -> Self:
        return cls.model_validate({"protected": value})

    def is_protected(self, branch: str) -> bool:
        return branch.strip().casefold() in self.protected

    def require_mutable(self, branch: str) -> str:
        value = branch.strip()
        if not value:
            raise ValueError("branch must not be empty")
        if self.is_protected(value):
            raise ProtectedBranchError(value)
        return value
