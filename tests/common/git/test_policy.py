from __future__ import annotations

import pytest

from common.git import ProtectedBranchError, ProtectedBranchPolicy


def test_policy_normalizes_case_and_whitespace() -> None:
    policy = ProtectedBranchPolicy.from_value({" Main ", "MASTER"})

    assert policy.protected == frozenset({"main", "master"})
    assert policy.is_protected("MAIN") is True
    assert policy.is_protected("feature/x") is False


def test_policy_accepts_comma_separated_configuration() -> None:
    policy = ProtectedBranchPolicy.from_value("main, production,main")

    assert policy.protected == frozenset({"main", "production"})


def test_policy_returns_normalized_input_branch_without_changing_case() -> None:
    policy = ProtectedBranchPolicy.from_value({"main"})

    assert policy.require_mutable(" Feature/ABC ") == "Feature/ABC"


def test_policy_rejects_empty_branch() -> None:
    policy = ProtectedBranchPolicy.from_value(set())

    with pytest.raises(ValueError, match="branch must not be empty"):
        policy.require_mutable("   ")


def test_policy_rejects_protected_branch_with_structured_error() -> None:
    policy = ProtectedBranchPolicy.from_value({"main"})

    with pytest.raises(ProtectedBranchError) as error:
        policy.require_mutable("MAIN")

    assert error.value.branch == "MAIN"
