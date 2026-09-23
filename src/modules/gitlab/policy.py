from __future__ import annotations

from common.config import env_list
from common.git import ProtectedBranchError, ProtectedBranchPolicy

from .errors import GitLabError


def protected_branches() -> set[str]:
    return set(env_list("GITLAB_PROTECTED_BRANCHES", "main,master"))


def require_mutable_branch(branch: str) -> str:
    policy = ProtectedBranchPolicy.from_value(protected_branches())
    try:
        return policy.require_mutable(branch)
    except ProtectedBranchError as exc:
        raise GitLabError(
            f"direct mutation of protected branch {exc.branch!r} is blocked; "
            "use a merge request"
        ) from exc
    except ValueError as exc:
        raise GitLabError(str(exc)) from exc
