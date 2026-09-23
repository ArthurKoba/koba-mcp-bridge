from __future__ import annotations

from collections.abc import Collection

from common.git import ProtectedBranchError, ProtectedBranchPolicy

from .errors import GitLabError


def require_mutable_branch(branch: str, protected_branches: Collection[str]) -> str:
    policy = ProtectedBranchPolicy.from_value(protected_branches)
    try:
        return policy.require_mutable(branch)
    except ProtectedBranchError as exc:
        raise GitLabError(
            f"direct mutation of protected branch {exc.branch!r} is blocked; use a merge request"
        ) from exc
    except ValueError as exc:
        raise GitLabError(str(exc)) from exc
