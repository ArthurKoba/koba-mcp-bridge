from __future__ import annotations

import urllib.parse

from common.models import (
    JsonObject,
    json_member_array,
    json_member_object,
    json_str,
)

from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError


def _parent_shas(commit: JsonObject) -> list[str]:
    result: list[str] = []
    for raw_parent in json_member_array(commit, "parents"):
        if not isinstance(raw_parent, dict):
            raise GitHubAgentError("git commit parent is malformed")
        sha = json_str(raw_parent.get("sha"))
        if not sha:
            raise GitHubAgentError("git commit parent has no sha")
        result.append(sha)
    return result


def _tree_sha(commit: JsonObject) -> str:
    tree = json_member_object(commit, "tree", required=True)
    sha = json_str(tree.get("sha"))
    if not sha:
        raise GitHubAgentError("git commit has no tree sha")
    return sha


def rewrite_branch_identity_graph(
    client: GitHubActionsClient,
    repository: str,
    branch: str,
    expected_head_sha: str,
    *,
    identity_source: str = "current_agent_app",
    preserve_messages: bool = True,
    preserve_trees: bool = True,
    preserve_author_dates: bool = True,
    max_commits: int = 500,
    dry_run: bool = True,
) -> JsonObject:
    """Rewrite an entire reachable commit DAG to the current Agent App identity."""
    repository = client._assert_allowed(repository)
    branch = client._assert_branch_mutation_allowed(repository, branch)
    expected_head_sha = expected_head_sha.strip()
    if identity_source != "current_agent_app":
        raise GitHubAgentError("identity_source must be current_agent_app")
    if not expected_head_sha:
        raise GitHubAgentError("expected_head_sha is required")
    if not preserve_messages or not preserve_trees:
        raise GitHubAgentError(
            "identity rewrite is identity-only; preserve_messages and preserve_trees must be true"
        )

    max_commits = max(1, min(max_commits, 2000))
    branch_q = urllib.parse.quote(branch, safe="")
    _, ref = client._repo_request(
        repository,
        "GET",
        f"/repos/{repository}/git/ref/heads/{branch_q}",
    )
    if not isinstance(ref, dict):
        raise GitHubAgentError("unable to resolve branch head")
    old_head = json_str(
        json_member_object(ref, "object", required=True).get("sha")
    )
    if old_head != expected_head_sha:
        raise GitHubAgentError(
            f"branch head changed: expected {expected_head_sha}, found {old_head}"
        )

    commits: dict[str, JsonObject] = {}
    order: list[str] = []
    visiting: set[str] = set()

    def visit(sha: str) -> None:
        if sha in commits:
            return
        if sha in visiting:
            raise GitHubAgentError(f"commit graph cycle detected at {sha}")
        if len(commits) + len(visiting) >= max_commits:
            raise GitHubAgentError(
                f"rewrite graph exceeds max_commits={max_commits}; raise the limit"
            )
        visiting.add(sha)
        commit = client._git_commit_object(repository, sha)
        for parent_sha in _parent_shas(commit):
            visit(parent_sha)
        visiting.remove(sha)
        commits[sha] = commit
        order.append(sha)

    visit(old_head)
    if not order:
        raise GitHubAgentError("rewrite graph contains no commits")

    identity = client._agent_app_identity()
    git_name = str(identity.get("name", ""))
    git_email = str(identity.get("email", ""))
    if not git_name or not git_email:
        raise GitHubAgentError("current Agent App identity is incomplete")

    mapping: dict[str, str] = {}
    plan: list[JsonObject] = []
    merge_commit_count = 0
    reused_commit_count = 0

    for old_sha in order:
        original = commits[old_sha]
        old_parents = _parent_shas(original)
        if len(old_parents) > 1:
            merge_commit_count += 1
        new_parents = [mapping[parent_sha] for parent_sha in old_parents]
        tree_sha = _tree_sha(original)
        message = json_str(original.get("message"))
        author = json_member_object(original, "author")
        committer = json_member_object(original, "committer")

        if client._identity_matches(original, git_name, git_email) and new_parents == old_parents:
            mapping[old_sha] = old_sha
            reused_commit_count += 1
            plan.append(
                {
                    "old_sha": old_sha,
                    "new_sha": old_sha,
                    "tree_sha": tree_sha,
                    "message": message,
                    "old_parent_shas": old_parents,
                    "new_parent_shas": new_parents,
                    "reused": True,
                }
            )
            continue

        author_payload: JsonObject = {"name": git_name, "email": git_email}
        committer_payload: JsonObject = {"name": git_name, "email": git_email}
        if preserve_author_dates:
            author_date = json_str(author.get("date"))
            committer_date = json_str(committer.get("date"))
            if author_date:
                author_payload["date"] = author_date
            if committer_date:
                committer_payload["date"] = committer_date

        payload: JsonObject = {
            "message": message,
            "tree": tree_sha,
            "parents": new_parents,
            "author": author_payload,
            "committer": committer_payload,
        }
        _, created = client._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/commits",
            payload=payload,
        )
        if not isinstance(created, dict):
            raise GitHubAgentError("GitHub did not return rewritten commit sha")
        new_sha = json_str(created.get("sha"))
        if not new_sha:
            raise GitHubAgentError("GitHub did not return rewritten commit sha")

        if _tree_sha(created) != tree_sha:
            raise GitHubAgentError(f"rewritten commit tree mismatch for {old_sha}")
        if json_str(created.get("message")) != message:
            raise GitHubAgentError(f"rewritten commit message mismatch for {old_sha}")
        if _parent_shas(created) != new_parents:
            raise GitHubAgentError(f"rewritten commit parent topology mismatch for {old_sha}")
        if not client._identity_matches(created, git_name, git_email):
            raise GitHubAgentError(f"rewritten commit identity mismatch for {old_sha}")

        mapping[old_sha] = new_sha
        plan.append(
            {
                "old_sha": old_sha,
                "new_sha": new_sha,
                "tree_sha": tree_sha,
                "message": message,
                "old_parent_shas": old_parents,
                "new_parent_shas": new_parents,
                "reused": False,
            }
        )

    if len(mapping) != len(order):
        raise GitHubAgentError("rewritten commit count does not match source graph commit count")

    new_head = mapping[old_head]
    old_head_tree = _tree_sha(commits[old_head])
    new_head_commit = client._git_commit_object(repository, new_head)
    new_head_tree = _tree_sha(new_head_commit)
    if new_head_tree != old_head_tree:
        raise GitHubAgentError(
            f"final tree mismatch: expected {old_head_tree}, found {new_head_tree}"
        )

    result: JsonObject = {
        "repository": repository,
        "branch": branch,
        "dry_run": dry_run,
        "dry_run_creates_unreferenced_commit_objects": dry_run,
        "identity_source": identity_source,
        "identity": identity,
        "old_head_sha": old_head,
        "new_head_sha": new_head,
        "commit_count": len(order),
        "merge_commit_count": merge_commit_count,
        "rewritten_commit_count": len(order) - reused_commit_count,
        "reused_commit_count": reused_commit_count,
        "preserve_messages": preserve_messages,
        "preserve_trees": preserve_trees,
        "preserve_author_dates": preserve_author_dates,
        "final_tree_sha": new_head_tree,
        "mapping": mapping,
        "plan": plan,
        "history_changed": new_head != old_head,
        "old_shas_reachable_from_new_head": any(
            old_sha == new_sha for old_sha, new_sha in mapping.items()
        ),
        "ref_updated": False,
    }
    if dry_run or new_head == old_head:
        return result

    _, ref_before_update = client._repo_request(
        repository,
        "GET",
        f"/repos/{repository}/git/ref/heads/{branch_q}",
    )
    if not isinstance(ref_before_update, dict):
        raise GitHubAgentError("unable to re-check branch head before graph rewrite")
    current_head = json_str(
        json_member_object(
            ref_before_update,
            "object",
            required=True,
        ).get("sha")
    )
    if current_head != expected_head_sha:
        raise GitHubAgentError(
            "branch head changed during graph rewrite: "
            f"expected {expected_head_sha}, found {current_head}"
        )

    client._repo_request(
        repository,
        "PATCH",
        f"/repos/{repository}/git/refs/heads/{branch_q}",
        payload={"sha": new_head, "force": True},
    )
    result["ref_updated"] = True
    return result
