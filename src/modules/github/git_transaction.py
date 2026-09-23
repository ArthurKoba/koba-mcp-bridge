from __future__ import annotations

from common.models import JsonObject, StrictModel, json_member_object, json_str

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError


class GitBranchTransaction(StrictModel):
    repository: str
    branch: str
    branch_ref: str
    head_sha: str
    base_tree_sha: str


class GitTransactionResult(StrictModel):
    previous_head_sha: str
    commit_sha: str
    tree_sha: str


class GitHubGitDataTransactionClient(GitHubRepositoryClientBase):
    def _resolve_commit_sha(self, repository: str, ref: str) -> str:
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError(f"unable to resolve ref: {ref}")
        sha = json_str(result.get("sha"))
        if not sha:
            raise GitHubAgentError(f"unable to resolve ref: {ref}")
        return sha

    def _resolve_commit_tree(self, repository: str, commit_sha: str) -> str:
        _, parent = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{self._quote(commit_sha)}",
        )
        if not isinstance(parent, dict):
            raise GitHubAgentError("unable to resolve parent tree")
        tree_sha = json_str(
            json_member_object(parent, "tree", required=True).get("sha")
        )
        if not tree_sha:
            raise GitHubAgentError("parent commit has no tree sha")
        return tree_sha

    def _begin_git_transaction(
        self,
        repository: str,
        branch: str,
        expected_head_sha: str | None = None,
    ) -> GitBranchTransaction:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        branch_ref = self._quote(branch)
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_ref}",
        )
        if not isinstance(ref, dict):
            raise GitHubAgentError("unable to resolve branch head")
        head_sha = json_str(
            json_member_object(ref, "object", required=True).get("sha")
        )
        if not head_sha:
            raise GitHubAgentError("branch head has no sha")
        if expected_head_sha and head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {head_sha}"
            )
        return GitBranchTransaction(
            repository=repository,
            branch=branch,
            branch_ref=branch_ref,
            head_sha=head_sha,
            base_tree_sha=self._resolve_commit_tree(repository, head_sha),
        )

    def _tree_entry_at_path(
        self,
        repository: str,
        root_tree_sha: str,
        path: str,
    ) -> JsonObject | None:
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            raise GitHubAgentError("path must not be empty")

        tree_sha = root_tree_sha
        for index, part in enumerate(parts):
            _, tree = self._repo_request(
                repository,
                "GET",
                f"/repos/{repository}/git/trees/{self._quote(tree_sha)}",
            )
            if not isinstance(tree, dict):
                raise GitHubAgentError("unexpected Git tree response")
            raw_entries = tree.get("tree")
            if not isinstance(raw_entries, list):
                raise GitHubAgentError("unexpected Git tree response")
            entry = next(
                (
                    item
                    for item in raw_entries
                    if isinstance(item, dict) and json_str(item.get("path")) == part
                ),
                None,
            )
            if entry is None:
                return None
            if index == len(parts) - 1:
                return entry
            if json_str(entry.get("type")) != "tree":
                return None
            tree_sha = json_str(entry.get("sha"))
            if not tree_sha:
                raise GitHubAgentError("Git tree entry has no sha")
        return None

    def _commit_tree_entries(
        self,
        transaction: GitBranchTransaction,
        message: str,
        tree_entries: list[JsonObject],
    ) -> GitTransactionResult:
        repository = transaction.repository
        _, tree = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/trees",
            payload={
                "base_tree": transaction.base_tree_sha,
                "tree": tree_entries,
            },
        )
        if not isinstance(tree, dict):
            raise GitHubAgentError("GitHub did not return a tree sha")
        tree_sha = json_str(tree.get("sha"))
        if not tree_sha:
            raise GitHubAgentError("GitHub did not return a tree sha")

        _, commit = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/commits",
            payload={
                "message": message,
                "tree": tree_sha,
                "parents": [transaction.head_sha],
            },
        )
        if not isinstance(commit, dict):
            raise GitHubAgentError("GitHub did not return a commit sha")
        commit_sha = json_str(commit.get("sha"))
        if not commit_sha:
            raise GitHubAgentError("GitHub did not return a commit sha")

        _, current_ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{transaction.branch_ref}",
        )
        current_object = (
            json_member_object(current_ref, "object")
            if isinstance(current_ref, dict)
            else {}
        )
        current_head_sha = json_str(current_object.get("sha"))
        if current_head_sha != transaction.head_sha:
            raise GitHubAgentError(
                "branch head changed before update: "
                f"expected {transaction.head_sha}, found {current_head_sha}"
            )

        self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{transaction.branch_ref}",
            payload={"sha": commit_sha, "force": False},
        )
        return GitTransactionResult(
            previous_head_sha=transaction.head_sha,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
        )
