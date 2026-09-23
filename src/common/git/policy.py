from __future__ import annotations

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
            items = value.split(",")
        elif isinstance(value, (set, frozenset, list, tuple)):
            items = value
        else:
            raise ValueError("protected branches must be a string or collection")
        return frozenset(
            str(item).strip().casefold()
            for item in items
            if str(item).strip()
        )

    def is_protected(self, branch: str) -> bool:
        return branch.strip().casefold() in self.protected

    def require_mutable(self, branch: str) -> str:
        value = branch.strip()
        if not value:
            raise ValueError("branch must not be empty")
        if self.is_protected(value):
            raise ProtectedBranchError(value)
        return value
