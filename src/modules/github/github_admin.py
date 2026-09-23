from __future__ import annotations

import urllib.parse

from common.models import (
    JsonObject,
    json_bool,
    json_member_object,
    json_object,
    json_str,
)

from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError
from .policy import protected_branches_from_env


def _tree_sha(commit: JsonObject) -> str:
    payload = json_object(commit, context="GitHub commit")
    tree = json_member_object(payload, "tree", required=True)
    sha = json_str(tree.get("sha"))
    if not sha:
        raise GitHubAgentError("commit has no tree sha")
    return sha


def repoint_reserved_branch(
    client: GitHubActionsClient,
    repository: str,
    branch: str,
    expected_head_sha: str,
    target_sha: str,
    *,
    dry_run: bool = True,
) -> JsonObject:
    """Repoint a Bridge-reserved branch without changing repository content.

    This is intentionally narrower than a general force-ref primitive. The target
    commit must have the same tree as the current reserved-branch head and must
    already carry the current Agent App Git identity. The branch must be reserved
    by Bridge policy, must not be the repository default branch, and must not be
    GitHub-protected. A compare-and-swap head check is repeated immediately before
    the forced ref update.
    """
    repository = client._assert_allowed(repository)
    branch = branch.strip()
    expected_head_sha = expected_head_sha.strip()
    target_sha = target_sha.strip()
    if not branch:
        raise GitHubAgentError("branch must not be empty")
    if not expected_head_sha:
        raise GitHubAgentError("expected_head_sha is required")
    if not target_sha:
        raise GitHubAgentError("target_sha is required")
    if branch.casefold() not in protected_branches_from_env():
        raise GitHubAgentError(
            f"branch is not reserved by bridge mutation policy: {branch}"
        )

    _, repo = client._repo_request(repository, "GET", f"/repos/{repository}")
    if not isinstance(repo, dict):
        raise GitHubAgentError("unexpected repository response")
    default_branch = json_str(repo.get("default_branch"))
    if default_branch and branch.casefold() == default_branch.casefold():
        raise GitHubAgentError(
            f"reserved-branch admin repoint refuses the repository default branch: {branch}"
        )

    branch_q = urllib.parse.quote(branch, safe="")
    _, branch_info = client._repo_request(
        repository,
        "GET",
        f"/repos/{repository}/branches/{branch_q}",
    )
    if not isinstance(branch_info, dict):
        raise GitHubAgentError("unexpected branch response")
    if json_bool(branch_info.get("protected")):
        raise GitHubAgentError(
            f"reserved branch is protected by GitHub and cannot be repointed here: {branch}"
        )

    _, ref = client._repo_request(
        repository,
        "GET",
        f"/repos/{repository}/git/ref/heads/{branch_q}",
    )
    try:
        ref_payload = json_object(ref, context="GitHub branch ref")
        ref_object = json_member_object(ref_payload, "object", required=True)
        old_head = json_str(ref_object.get("sha"))
    except ValueError as exc:
        raise GitHubAgentError("unable to resolve reserved branch head") from exc
    if old_head != expected_head_sha:
        raise GitHubAgentError(
            f"branch head changed: expected {expected_head_sha}, found {old_head}"
        )

    old_commit = client._git_commit_object(repository, old_head)
    target_commit = client._git_commit_object(repository, target_sha)
    old_tree = _tree_sha(old_commit)
    target_tree = _tree_sha(target_commit)
    if old_tree != target_tree:
        raise GitHubAgentError(
            "reserved-branch repoint would change repository content; "
            f"current_tree={old_tree}, target_tree={target_tree}"
        )

    identity = client._agent_app_identity()
    identity_name = str(identity.get("name", ""))
    identity_email = str(identity.get("email", ""))
    if not client._identity_matches(target_commit, identity_name, identity_email):
        raise GitHubAgentError(
            "target commit does not use the current Agent App identity; "
            f"target_sha={target_sha}"
        )

    result: JsonObject = {
        "repository": repository,
        "branch": branch,
        "old_head_sha": old_head,
        "new_head_sha": target_sha,
        "tree_sha": old_tree,
        "content_changed": False,
        "bridge_reserved": True,
        "github_protected": False,
        "agent_identity": identity,
        "dry_run": dry_run,
        "ref_updated": False,
    }
    if old_head == target_sha:
        result["status"] = "already_at_target"
        return result
    if dry_run:
        result["status"] = "ready"
        return result

    _, current_ref = client._repo_request(
        repository,
        "GET",
        f"/repos/{repository}/git/ref/heads/{branch_q}",
    )
    try:
        current_payload = json_object(current_ref, context="GitHub branch ref")
        current_object = json_member_object(current_payload, "object", required=True)
        current_head = json_str(current_object.get("sha"))
    except ValueError as exc:
        raise GitHubAgentError("unable to re-check reserved branch head") from exc
    if current_head != expected_head_sha:
        raise GitHubAgentError(
            "reserved branch changed during repoint; "
            f"expected {expected_head_sha}, found {current_head}"
        )

    client._repo_request(
        repository,
        "PATCH",
        f"/repos/{repository}/git/refs/heads/{branch_q}",
        payload={"sha": target_sha, "force": True},
    )
    result["ref_updated"] = True
    result["status"] = "updated"
    return result
