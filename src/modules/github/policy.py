from __future__ import annotations

from collections.abc import Collection

from common.git import ProtectedBranchError, ProtectedBranchPolicy

from .github_agent import GitHubAgentError


def require_mutable_branch(branch: str, protected_branches: Collection[str]) -> str:
    policy = ProtectedBranchPolicy.from_value(protected_branches)
    try:
        return policy.require_mutable(branch)
    except ProtectedBranchError as exc:
        raise GitHubAgentError(
            f"direct mutation of protected branch is disabled: {exc.branch}; use a pull request"
        ) from exc
    except ValueError as exc:
        raise GitHubAgentError(str(exc)) from exc
