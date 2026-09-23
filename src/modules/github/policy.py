from __future__ import annotations

import os

from common.config import env_list
from common.git import ProtectedBranchError, ProtectedBranchPolicy
from common.secrets import SecretError, resolve_config_secret

from .github_agent import GitHubAgentError

_DEFAULT_PROTECTED_BRANCHES = "main,master"
_DEFAULT_REQUIRED_CHECKS = "test,docker"


def protected_branches_from_env() -> set[str]:
    try:
        raw = resolve_config_secret(
            "github/development",
            "PROTECTED_BRANCHES",
        )
    except SecretError:
        raw = os.getenv(
            "GITHUB_AGENT_PROTECTED_BRANCHES",
            _DEFAULT_PROTECTED_BRANCHES,
        )
    return set(ProtectedBranchPolicy.from_value(raw).protected)


def require_mutable_branch(branch: str) -> str:
    policy = ProtectedBranchPolicy.from_value(protected_branches_from_env())
    try:
        return policy.require_mutable(branch)
    except ProtectedBranchError as exc:
        raise GitHubAgentError(
            f"direct mutation of protected branch is disabled: {exc.branch}; "
            "use a pull request"
        ) from exc
    except ValueError as exc:
        raise GitHubAgentError(str(exc)) from exc


def required_checks_from_env() -> list[str]:
    return env_list("GITHUB_AGENT_REQUIRED_CHECKS", _DEFAULT_REQUIRED_CHECKS)
