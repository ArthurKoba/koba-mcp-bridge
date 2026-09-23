from __future__ import annotations

import base64
import os
import urllib.parse

from common.config import env_list
from common.models import JsonObject
from common.secrets import SecretError, resolve_config_secret

from .github_agent import GitHubAgentError, GitHubAppClient
from .models import AtomicChange, CopySpec

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
    return {
        item.strip().casefold()
        for item in raw.split(",")
        if item.strip()
    }


def required_checks_from_env() -> list[str]:
    return env_list("GITHUB_AGENT_REQUIRED_CHECKS", _DEFAULT_REQUIRED_CHECKS)


class GitHubDevClient(GitHubAppClient):
    """Development-oriented GitHub App client with repository policy guardrails."""

    def _assert_mutable_branch(self, branch: str) -> str:
        branch = branch.strip()
        if not branch:
            raise GitHubAgentError("branch must not be empty")
        if branch.casefold() in protected_branches_from_env():
            raise GitHubAgentError(
                f"direct mutation of protected branch is disabled: {branch}; use a pull request"
            )
        return branch

    @staticmethod
    def _quote(value: str) -> str:
        return urllib.parse.quote(value, safe="")

    @staticmethod
    def _path(path: str) -> str:
        return urllib.parse.quote(path.strip("/"), safe="/")

    def list_directory(
        self,
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        suffix = self._path(path)
        endpoint = f"/repos/{repository}/contents"
        if suffix:
            endpoint += f"/{suffix}"
        if ref:
            endpoint += "?ref=" + self._quote(ref)
        _, result = self._repo_request(repository, "GET", endpoint)
        if not isinstance(result, list):
            raise GitHubAgentError("path is not a directory")
        entries = [
            {
                "name": str(item.get("name", "")),
                "path": str(item.get("path", "")),
                "type": str(item.get("type", "")),
                "size": int(item.get("size", 0)),
                "sha": str(item.get("sha", "")),
            }
            for item in result
            if isinstance(item, dict)
        ]
        return {"repository": repository, "path": path, "ref": ref, "entries": entries}

    def get_binary_file(
        self,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        endpoint = f"/repos/{repository}/contents/{self._path(path)}"
        if ref:
            endpoint += "?ref=" + self._quote(ref)
        _, result = self._repo_request(repository, "GET", endpoint)
        if not isinstance(result, dict) or result.get("type") != "file":
            raise GitHubAgentError("path is not a regular file")
        if str(result.get("encoding", "")) != "base64":
            raise GitHubAgentError("GitHub did not return base64 file content")
        return {
            "repository": repository,
            "path": str(result.get("path", path)),
            "sha": str(result.get("sha", "")),
            "size": int(result.get("size", 0)),
            "content_base64": str(result.get("content", "")).replace("\n", ""),
        }

    def put_file(
        self,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        self._assert_mutable_branch(branch)
        return super().put_file(repository, path, content, message, branch)

    def put_binary_file(
        self,
        repository: str,
        path: str,
        content_base64: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        try:
            base64.b64decode(content_base64, validate=True)
        except ValueError as exc:
            raise GitHubAgentError("content_base64 is not valid base64") from exc
        quoted_path = self._path(path)
        ref = self._quote(branch)
        status, current = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{quoted_path}?ref={ref}",
            allowed_errors={404},
        )
        payload: dict[str, object] = {
            "message": message,
            "content": content_base64,
            "branch": branch,
        }
        operation = "create"
        if status != 404:
            if not isinstance(current, dict) or current.get("type") != "file":
                raise GitHubAgentError("existing path is not a regular file")
            payload["sha"] = str(current.get("sha", ""))
            operation = "update"
        response_status, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/contents/{quoted_path}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected binary file write response")
        commit = result.get("commit") if isinstance(result.get("commit"), dict) else {}
        saved = result.get("content") if isinstance(result.get("content"), dict) else {}
        return {
            "status": response_status,
            "operation": operation,
            "repository": repository,
            "branch": branch,
            "path": path,
            "commit_sha": str(commit.get("sha", "")),
            "content_sha": str(saved.get("sha", "")),
        }

    def _tree_entry_at_path(
        self,
        repository: str,
        root_tree_sha: str,
        path: str,
    ) -> dict[str, object] | None:
        """Resolve one tree entry by path without reading blob contents."""
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
            if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
                raise GitHubAgentError("unexpected Git tree response")
            entry = next(
                (
                    item
                    for item in tree["tree"]
                    if isinstance(item, dict) and str(item.get("path", "")) == part
                ),
                None,
            )
            if entry is None:
                return None
            if index == len(parts) - 1:
                return dict(entry)
            if str(entry.get("type", "")) != "tree":
                return None
            tree_sha = str(entry.get("sha", ""))
            if not tree_sha:
                raise GitHubAgentError("Git tree entry has no sha")
        return None

    def copy_files(
        self,
        repository: str,
        source_ref: str,
        branch: str,
        message: str,
        copies: list[CopySpec],
        expected_head_sha: str | None = None,
        operation: str = "copy",
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Copy or move existing Git blobs without transferring file contents."""
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        source_ref = source_ref.strip()
        operation = operation.strip().casefold()
        if not source_ref:
            raise GitHubAgentError("source_ref must not be empty")
        if not copies:
            raise GitHubAgentError("copies must not be empty")
        if operation not in {"copy", "move"}:
            raise GitHubAgentError("operation must be 'copy' or 'move'")

        _, source_commit = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(source_ref)}",
        )
        if not isinstance(source_commit, dict) or not source_commit.get("sha"):
            raise GitHubAgentError("unable to resolve source_ref")
        source_sha = str(source_commit["sha"])

        branch_q = self._quote(branch)
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
            raise GitHubAgentError("unable to resolve branch head")
        head_sha = str(ref["object"].get("sha", ""))
        if not head_sha:
            raise GitHubAgentError("branch head has no sha")
        if expected_head_sha and head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {head_sha}"
            )
        if operation == "move" and source_sha != head_sha:
            raise GitHubAgentError(
                "move requires source_ref to resolve to the current destination branch HEAD"
            )

        _, parent = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{head_sha}",
        )
        if not isinstance(parent, dict) or not isinstance(parent.get("tree"), dict):
            raise GitHubAgentError("unable to resolve parent tree")
        base_tree = str(parent["tree"].get("sha", ""))
        if not base_tree:
            raise GitHubAgentError("parent commit has no tree sha")

        source_tree = base_tree
        if source_sha != head_sha:
            _, source_git_commit = self._repo_request(
                repository,
                "GET",
                f"/repos/{repository}/git/commits/{source_sha}",
            )
            if (
                not isinstance(source_git_commit, dict)
                or not isinstance(source_git_commit.get("tree"), dict)
            ):
                raise GitHubAgentError("unable to resolve source commit tree")
            source_tree = str(source_git_commit["tree"].get("sha", ""))
            if not source_tree:
                raise GitHubAgentError("source commit has no tree sha")

        tree_entries: list[dict[str, object]] = []
        seen_destinations: set[str] = set()
        seen_move_sources: set[str] = set()
        processed: list[dict[str, object]] = []

        for item in copies:
            source_path = "/".join(
                part
                for part in item.source_path.strip("/").split("/")
                if part
            )
            destination_path = "/".join(
                part
                for part in item.destination_path.strip("/").split("/")
                if part
            )
            if not source_path or not destination_path:
                raise GitHubAgentError(
                    "every copy requires source_path and destination_path"
                )
            if source_path == destination_path:
                raise GitHubAgentError(
                    "source_path and destination_path must be different"
                )
            if destination_path in seen_destinations:
                raise GitHubAgentError(
                    f"duplicate destination_path: {destination_path}"
                )
            seen_destinations.add(destination_path)
            if operation == "move":
                if source_path in seen_move_sources:
                    raise GitHubAgentError(f"duplicate move source_path: {source_path}")
                seen_move_sources.add(source_path)

            source = self._tree_entry_at_path(
                repository,
                source_tree,
                source_path,
            )
            if source is None or str(source.get("type", "")) != "blob":
                raise GitHubAgentError(
                    f"source path is not a Git blob: {source_path}"
                )
            blob_sha = str(source.get("sha", ""))
            source_mode = str(source.get("mode", ""))
            if not blob_sha or not source_mode:
                raise GitHubAgentError(
                    f"source blob is missing sha or mode: {source_path}"
                )
            mode = item.mode or source_mode

            destination = self._tree_entry_at_path(
                repository,
                base_tree,
                destination_path,
            )
            if destination is not None:
                if not overwrite:
                    raise GitHubAgentError(
                        f"destination_path already exists: {destination_path}"
                    )
                if str(destination.get("type", "")) != "blob":
                    raise GitHubAgentError(
                        f"destination_path is not a blob: {destination_path}"
                    )

            tree_entries.append(
                {
                    "path": destination_path,
                    "mode": mode,
                    "type": "blob",
                    "sha": blob_sha,
                }
            )
            if operation == "move":
                tree_entries.append(
                    {
                        "path": source_path,
                        "mode": source_mode,
                        "type": "blob",
                        "sha": None,
                    }
                )
            processed.append(
                {
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "sha": blob_sha,
                    "mode": mode,
                    "size": int(source.get("size", 0)),
                }
            )

        _, tree = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/trees",
            payload={"base_tree": base_tree, "tree": tree_entries},
        )
        if not isinstance(tree, dict) or not tree.get("sha"):
            raise GitHubAgentError("GitHub did not return a tree sha")
        tree_sha = str(tree["sha"])

        _, new_commit = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/commits",
            payload={"message": message, "tree": tree_sha, "parents": [head_sha]},
        )
        if not isinstance(new_commit, dict) or not new_commit.get("sha"):
            raise GitHubAgentError("GitHub did not return a commit sha")
        commit_sha = str(new_commit["sha"])

        _, current_ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        current_object = (
            current_ref.get("object")
            if isinstance(current_ref, dict)
            and isinstance(current_ref.get("object"), dict)
            else {}
        )
        current_head_sha = str(current_object.get("sha", ""))
        if current_head_sha != head_sha:
            raise GitHubAgentError(
                f"branch head changed before update: expected {head_sha}, "
                f"found {current_head_sha}"
            )

        self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": commit_sha, "force": False},
        )
        return {
            "repository": repository,
            "source_ref": source_ref,
            "source_sha": source_sha,
            "branch": branch,
            "operation": operation,
            "previous_head_sha": head_sha,
            "commit_sha": commit_sha,
            "tree_sha": tree_sha,
            "copied": processed if operation == "copy" else [],
            "moved": processed if operation == "move" else [],
        }

    def delete_file(
        self,
        repository: str,
        path: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        self._assert_mutable_branch(branch)
        return super().delete_file(repository, path, message, branch)

    def commit_files(
        self,
        repository: str,
        branch: str,
        message: str,
        changes: list[AtomicChange],
        expected_head_sha: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        if not changes:
            raise GitHubAgentError("changes must not be empty")

        branch_q = self._quote(branch)
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
            raise GitHubAgentError("unable to resolve branch head")
        head_sha = str(ref["object"].get("sha", ""))
        if not head_sha:
            raise GitHubAgentError("branch head has no sha")
        if expected_head_sha and head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {head_sha}"
            )

        _, parent = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{head_sha}",
        )
        if not isinstance(parent, dict) or not isinstance(parent.get("tree"), dict):
            raise GitHubAgentError("unable to resolve parent tree")
        base_tree = str(parent["tree"].get("sha", ""))
        if not base_tree:
            raise GitHubAgentError("parent commit has no tree sha")

        tree_entries: list[dict[str, object]] = []
        copy_ref_cache: dict[str, str] = {}
        for change in changes:
            path = change.path.strip("/")
            operation = change.operation
            mode = change.mode
            if operation == "delete":
                tree_entries.append(
                    {"path": path, "mode": mode, "type": "blob", "sha": None}
                )
                continue
            if operation == "copy":
                source_path = (change.source_path or "").strip("/")
                source_ref = (change.source_ref or "").strip()

                source_sha = copy_ref_cache.get(source_ref)
                if source_sha is None:
                    _, source_commit = self._repo_request(
                        repository,
                        "GET",
                        f"/repos/{repository}/commits/{self._quote(source_ref)}",
                    )
                    if (
                        not isinstance(source_commit, dict)
                        or not source_commit.get("sha")
                    ):
                        raise GitHubAgentError(
                            f"unable to resolve source_ref: {source_ref}"
                        )
                    source_sha = str(source_commit["sha"])
                    copy_ref_cache[source_ref] = source_sha

                _, source = self._repo_request(
                    repository,
                    "GET",
                    (
                        f"/repos/{repository}/contents/{self._path(source_path)}"
                        f"?ref={self._quote(source_sha)}"
                    ),
                )
                if not isinstance(source, dict) or source.get("type") != "file":
                    raise GitHubAgentError(
                        f"copy source is not a regular file: {source_path}"
                    )
                blob_sha = str(source.get("sha", ""))
                if not blob_sha:
                    raise GitHubAgentError(
                        f"copy source has no blob sha: {source_path}"
                    )
                tree_entries.append(
                    {
                        "path": path,
                        "mode": mode,
                        "type": "blob",
                        "sha": blob_sha,
                    }
                )
                continue
            if operation not in {"upsert", "create", "update"}:
                raise GitHubAgentError(f"unsupported change operation: {operation}")

            text = change.content
            encoded = change.content_base64
            if encoded is not None:
                blob_payload = {"content": str(encoded), "encoding": "base64"}
            else:
                blob_payload = {"content": str(text), "encoding": "utf-8"}
            _, blob = self._repo_request(
                repository,
                "POST",
                f"/repos/{repository}/git/blobs",
                payload=blob_payload,
            )
            if not isinstance(blob, dict) or not blob.get("sha"):
                raise GitHubAgentError("GitHub did not return a blob sha")
            tree_entries.append(
                {
                    "path": path,
                    "mode": mode,
                    "type": "blob",
                    "sha": str(blob["sha"]),
                }
            )

        _, tree = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/trees",
            payload={"base_tree": base_tree, "tree": tree_entries},
        )
        if not isinstance(tree, dict) or not tree.get("sha"):
            raise GitHubAgentError("GitHub did not return a tree sha")
        tree_sha = str(tree["sha"])

        _, commit = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/commits",
            payload={"message": message, "tree": tree_sha, "parents": [head_sha]},
        )
        if not isinstance(commit, dict) or not commit.get("sha"):
            raise GitHubAgentError("GitHub did not return a commit sha")
        commit_sha = str(commit["sha"])

        self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": commit_sha, "force": False},
        )
        return {
            "repository": repository,
            "branch": branch,
            "previous_head_sha": head_sha,
            "commit_sha": commit_sha,
            "tree_sha": tree_sha,
            "changed_paths": [change.path for change in changes],
        }

    def list_commits(
        self,
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        params: dict[str, str | int] = {
            "per_page": max(1, min(per_page, 100)),
            "page": max(1, page),
        }
        if ref:
            params["sha"] = ref
        if path:
            params["path"] = path
        query = urllib.parse.urlencode(params)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits?{query}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected commit list response")
        commits = []
        for item in result:
            if not isinstance(item, dict):
                continue
            details = item.get("commit") if isinstance(item.get("commit"), dict) else {}
            author = details.get("author") if isinstance(details.get("author"), dict) else {}
            commits.append(
                {
                    "sha": str(item.get("sha", "")),
                    "message": str(details.get("message", "")),
                    "author": str(author.get("name", "")),
                    "date": str(author.get("date", "")),
                }
            )
        return {"repository": repository, "commits": commits, "page": page}

    def get_commit(self, repository: str, ref: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected commit response")
        details = result.get("commit") if isinstance(result.get("commit"), dict) else {}
        files = result.get("files") if isinstance(result.get("files"), list) else []
        return {
            "repository": repository,
            "sha": str(result.get("sha", "")),
            "message": str(details.get("message", "")),
            "parents": [
                str(item.get("sha", ""))
                for item in result.get("parents", [])
                if isinstance(item, dict)
            ],
            "files": [
                {
                    "filename": str(item.get("filename", "")),
                    "status": str(item.get("status", "")),
                    "additions": int(item.get("additions", 0)),
                    "deletions": int(item.get("deletions", 0)),
                    "patch": item.get("patch"),
                }
                for item in files
                if isinstance(item, dict)
            ],
        }

    def delete_branch(self, repository: str, branch: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/git/refs/heads/{self._quote(branch)}",
        )
        return {"repository": repository, "branch": branch, "deleted": True}

    def rename_branch(
        self,
        repository: str,
        branch: str,
        new_name: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        new_name = self._assert_mutable_branch(new_name)
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/branches/{self._quote(branch)}/rename",
            payload={"new_name": new_name},
        )
        return {
            "repository": repository,
            "old_branch": branch,
            "new_branch": new_name,
            "result": result,
        }

    def fast_forward(self, repository: str, branch: str, to_ref: str) -> dict[str, object]:
        self._assert_mutable_branch(branch)
        return super().fast_forward(repository, branch, to_ref)

    def reset_branch(
        self,
        repository: str,
        branch: str,
        target_ref: str,
        expected_head_sha: str,
        allow_protected_branch: bool = False,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Force-reset a branch to an existing ancestor commit with CAS safeguards."""
        repository = self._assert_allowed(repository)
        branch = branch.strip()
        target_ref = target_ref.strip()
        expected_head_sha = expected_head_sha.strip()
        if not branch:
            raise GitHubAgentError("branch must not be empty")
        if not target_ref:
            raise GitHubAgentError("target_ref must not be empty")
        if not expected_head_sha:
            raise GitHubAgentError("expected_head_sha must not be empty")
        if (
            branch.casefold() in protected_branches_from_env()
            and not allow_protected_branch
        ):
            raise GitHubAgentError(
                f"reset of protected branch requires allow_protected_branch=true: {branch}"
            )

        branch_q = self._quote(branch)
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
            raise GitHubAgentError("unable to resolve branch head")
        head_sha = str(ref["object"].get("sha", ""))
        if not head_sha:
            raise GitHubAgentError("branch head has no sha")
        if head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {head_sha}"
            )

        _, target = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(target_ref)}",
        )
        if not isinstance(target, dict) or not target.get("sha"):
            raise GitHubAgentError("unable to resolve target_ref")
        target_sha = str(target["sha"])

        if target_sha != head_sha:
            _, comparison = self._repo_request(
                repository,
                "GET",
                (
                    f"/repos/{repository}/compare/"
                    f"{self._quote(target_sha)}...{self._quote(head_sha)}"
                ),
            )
            if not isinstance(comparison, dict):
                raise GitHubAgentError("unexpected compare response")
            if (
                str(comparison.get("status", "")) != "ahead"
                or int(comparison.get("behind_by", 0)) != 0
            ):
                raise GitHubAgentError(
                    "target_ref must resolve to an ancestor of the current branch head"
                )

        result = {
            "repository": repository,
            "branch": branch,
            "previous_head_sha": head_sha,
            "target_ref": target_ref,
            "target_sha": target_sha,
            "protected_branch_override": allow_protected_branch,
            "dry_run": dry_run,
        }
        if dry_run or target_sha == head_sha:
            return result

        _, current_ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        current_object = (
            current_ref.get("object")
            if isinstance(current_ref, dict)
            and isinstance(current_ref.get("object"), dict)
            else {}
        )
        current_head_sha = str(current_object.get("sha", ""))
        if current_head_sha != head_sha:
            raise GitHubAgentError(
                f"branch head changed before reset: expected {head_sha}, "
                f"found {current_head_sha}"
            )

        _, updated = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": target_sha, "force": True},
        )
        return {**result, "dry_run": False, "result": updated}

    def list_tags(
        self,
        repository: str,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        params = urllib.parse.urlencode(
            {"per_page": max(1, min(per_page, 100)), "page": max(1, page)}
        )
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/tags?{params}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected tag list response")
        tags = []
        for item in result:
            if isinstance(item, dict):
                commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
                tags.append({"name": str(item.get("name", "")), "sha": str(commit.get("sha", ""))})
        return {"repository": repository, "tags": tags, "page": page}

    def create_tag(
        self,
        repository: str,
        tag: str,
        target_ref: str,
        message: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, target = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(target_ref)}",
        )
        if not isinstance(target, dict) or not target.get("sha"):
            raise GitHubAgentError("unable to resolve tag target")
        target_sha = str(target["sha"])
        ref_sha = target_sha
        annotated = bool(message)
        if message:
            _, tag_obj = self._repo_request(
                repository,
                "POST",
                f"/repos/{repository}/git/tags",
                payload={
                    "tag": tag,
                    "message": message,
                    "object": target_sha,
                    "type": "commit",
                },
            )
            if not isinstance(tag_obj, dict) or not tag_obj.get("sha"):
                raise GitHubAgentError("GitHub did not return an annotated tag sha")
            ref_sha = str(tag_obj["sha"])
        self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/refs",
            payload={"ref": f"refs/tags/{tag}", "sha": ref_sha},
        )
        return {
            "repository": repository,
            "tag": tag,
            "target_sha": target_sha,
            "annotated": annotated,
        }

    def delete_tag(self, repository: str, tag: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/git/refs/tags/{self._quote(tag)}",
        )
        return {"repository": repository, "tag": tag, "deleted": True}

    def search_code(
        self,
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        q = f"{query} repo:{repository}"
        params = urllib.parse.urlencode(
            {
                "q": q,
                "per_page": max(1, min(per_page, 100)),
                "page": max(1, page),
            }
        )
        _, result = self._repo_request(repository, "GET", f"/search/code?{params}")
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected code search response")
        items = result.get("items") if isinstance(result.get("items"), list) else []
        return {
            "repository": repository,
            "total_count": int(result.get("total_count", 0)),
            "items": [
                {
                    "name": str(item.get("name", "")),
                    "path": str(item.get("path", "")),
                    "sha": str(item.get("sha", "")),
                }
                for item in items
                if isinstance(item, dict)
            ],
            "page": page,
        }

    def list_pull_requests(
        self,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubAgentError("state must be open, closed, or all")
        params = urllib.parse.urlencode(
            {
                "state": state,
                "per_page": max(1, min(per_page, 100)),
                "page": max(1, page),
            }
        )
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls?{params}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request list response")
        return {
            "repository": repository,
            "pull_requests": [self._compact_pull(item) for item in result if isinstance(item, dict)],
            "page": page,
        }

    @staticmethod
    def _compact_pull(item: JsonObject) -> dict[str, object]:
        head = item.get("head") if isinstance(item.get("head"), dict) else {}
        base = item.get("base") if isinstance(item.get("base"), dict) else {}
        return {
            "number": int(item.get("number", 0)),
            "title": str(item.get("title", "")),
            "state": str(item.get("state", "")),
            "draft": bool(item.get("draft", False)),
            "head": str(head.get("ref", "")),
            "head_sha": str(head.get("sha", "")),
            "base": str(base.get("ref", "")),
            "merged": bool(item.get("merged", False)),
            "html_url": str(item.get("html_url", "")),
        }

    def get_pull_request(self, repository: str, number: int) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request response")
        compact = self._compact_pull(result)
        compact["body"] = str(result.get("body", "") or "")
        compact["mergeable"] = result.get("mergeable")
        compact["mergeable_state"] = str(result.get("mergeable_state", ""))
        return {"repository": repository, "pull_request": compact}

    def create_pull_request(
        self,
        repository: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        if ":" in head or ":" in base:
            raise GitHubAgentError("cross-repository pull requests are disabled")
        if head == base:
            raise GitHubAgentError("pull request head and base must differ")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls",
            payload={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request create response")
        return {"repository": repository, "pull_request": self._compact_pull(result)}

    def update_pull_request(
        self,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        payload: dict[str, object] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            if state not in {"open", "closed"}:
                raise GitHubAgentError("state must be open or closed")
            payload["state"] = state
        if base is not None:
            if ":" in base:
                raise GitHubAgentError("cross-repository pull requests are disabled")
            payload["base"] = base
        if not payload:
            raise GitHubAgentError("no pull request fields were supplied")
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/pulls/{number}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request update response")
        return {"repository": repository, "pull_request": self._compact_pull(result)}

    def list_pull_files(self, repository: str, number: int) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/files?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request file response")
        files = [
            {
                "filename": str(item.get("filename", "")),
                "status": str(item.get("status", "")),
                "additions": int(item.get("additions", 0)),
                "deletions": int(item.get("deletions", 0)),
                "patch": item.get("patch"),
            }
            for item in result
            if isinstance(item, dict)
        ]
        return {"repository": repository, "number": number, "files": files}

    def add_pull_comment(
        self,
        repository: str,
        number: int,
        body: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            payload={"body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request comment response")
        return {
            "repository": repository,
            "number": number,
            "comment_id": int(result.get("id", 0)),
            "html_url": str(result.get("html_url", "")),
        }

    def list_reviews(self, repository: str, number: int) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request review response")
        reviews = []
        for item in result:
            if not isinstance(item, dict):
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            reviews.append(
                {
                    "id": int(item.get("id", 0)),
                    "user": str(user.get("login", "")),
                    "state": str(item.get("state", "")),
                    "body": str(item.get("body", "") or ""),
                    "submitted_at": str(item.get("submitted_at", "")),
                }
            )
        return {"repository": repository, "number": number, "reviews": reviews}

    def create_review(
        self,
        repository: str,
        number: int,
        event: str,
        body: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        event = event.upper()
        if event not in {"APPROVE", "REQUEST_CHANGES", "COMMENT"}:
            raise GitHubAgentError("event must be APPROVE, REQUEST_CHANGES, or COMMENT")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/reviews",
            payload={"event": event, "body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected review create response")
        return {
            "repository": repository,
            "number": number,
            "review_id": int(result.get("id", 0)),
            "state": str(result.get("state", "")),
        }

    def update_pull_branch(
        self,
        repository: str,
        number: int,
        expected_head_sha: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        payload: dict[str, object] = {}
        if expected_head_sha:
            payload["expected_head_sha"] = expected_head_sha
        _, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{number}/update-branch",
            payload=payload,
        )
        return {"repository": repository, "number": number, "result": result}

    def check_runs(self, repository: str, ref: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}/check-runs?per_page=100",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected check-run response")
        raw = result.get("check_runs") if isinstance(result.get("check_runs"), list) else []
        checks = []
        for item in raw:
            if isinstance(item, dict):
                app = item.get("app") if isinstance(item.get("app"), dict) else {}
                checks.append(
                    {
                        "name": str(item.get("name", "")),
                        "status": str(item.get("status", "")),
                        "conclusion": item.get("conclusion"),
                        "app": str(app.get("slug", "")),
                        "details_url": str(item.get("details_url", "")),
                    }
                )
        return {"repository": repository, "ref": ref, "check_runs": checks}

    def assert_required_checks(self, repository: str, ref: str) -> dict[str, object]:
        result = self.check_runs(repository, ref)
        checks = result["check_runs"]
        assert isinstance(checks, list)
        by_name = {
            str(item.get("name", "")): item
            for item in checks
            if isinstance(item, dict)
        }
        required = required_checks_from_env()

        # The bridge can serve multiple repositories whose CI check names are
        # unrelated. GITHUB_AGENT_REQUIRED_CHECKS is therefore only applicable
        # when at least one configured check name is part of this repository's
        # normal CI surface. If the PR head has none of them, inspect the
        # repository's default branch before deciding that they are "missing".
        #
        # This keeps the strict test/docker gate for mcp-bridge while
        # avoiding an impossible merge requirement on repositories such as
        # ghidra-mcp, whose aggregate check is named "Build Status". GitHub's
        # own branch protection/rulesets remain the final merge authority.
        configured_names = set(required)
        if configured_names and not configured_names.intersection(by_name):
            repository_info = self._repository_metadata(repository)
            default_branch = str(repository_info.get("default_branch", ""))
            baseline_names: set[str] = set()
            if default_branch:
                baseline = self.check_runs(repository, default_branch)
                baseline_checks = baseline["check_runs"]
                assert isinstance(baseline_checks, list)
                baseline_names = {
                    str(item.get("name", ""))
                    for item in baseline_checks
                    if isinstance(item, dict)
                }
            if not configured_names.intersection(baseline_names):
                return {
                    "repository": repository,
                    "ref": ref,
                    "required": required,
                    "status": "delegated_to_github",
                }

        missing = [name for name in required if name not in by_name]
        failing = [
            name
            for name in required
            if name in by_name
            and (
                by_name[name].get("status") != "completed"
                or by_name[name].get("conclusion") != "success"
            )
        ]
        if missing or failing:
            raise GitHubAgentError(
                f"required checks not satisfied; missing={missing}, failing={failing}"
            )
        return {"repository": repository, "ref": ref, "required": required, "status": "ok"}

    def merge_pull_request(
        self,
        repository: str,
        number: int,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        if merge_method not in {"merge", "squash", "rebase"}:
            raise GitHubAgentError("merge_method must be merge, squash, or rebase")
        _, pull = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(pull, dict):
            raise GitHubAgentError("unexpected pull request response")
        head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
        base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
        base_repo = base.get("repo") if isinstance(base.get("repo"), dict) else {}
        if str(head_repo.get("full_name", "")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request merge is disabled")
        if str(base_repo.get("full_name", "")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request merge is disabled")
        head_sha = str(head.get("sha", ""))
        if not head_sha:
            raise GitHubAgentError("pull request head has no sha")
        self.assert_required_checks(repository, head_sha)

        payload: dict[str, object] = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        _, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{number}/merge",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request merge response")
        return {
            "repository": repository,
            "number": number,
            "merged": bool(result.get("merged", False)),
            "sha": str(result.get("sha", "")),
            "message": str(result.get("message", "")),
            "merge_method": merge_method,
        }

    def list_issues(
        self,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubAgentError("state must be open, closed, or all")
        params = urllib.parse.urlencode(
            {
                "state": state,
                "per_page": max(1, min(per_page, 100)),
                "page": max(1, page),
            }
        )
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/issues?{params}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected issue list response")
        issues = []
        for item in result:
            if not isinstance(item, dict) or "pull_request" in item:
                continue
            issues.append(self._compact_issue(item))
        return {"repository": repository, "issues": issues, "page": page}

    @staticmethod
    def _compact_issue(item: JsonObject) -> dict[str, object]:
        return {
            "number": int(item.get("number", 0)),
            "title": str(item.get("title", "")),
            "state": str(item.get("state", "")),
            "body": str(item.get("body", "") or ""),
            "html_url": str(item.get("html_url", "")),
        }

    def get_issue(self, repository: str, number: int) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/issues/{number}",
        )
        if not isinstance(result, dict) or "pull_request" in result:
            raise GitHubAgentError("number does not refer to an issue")
        return {"repository": repository, "issue": self._compact_issue(result)}

    def create_issue(
        self,
        repository: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        payload: dict[str, object] = {"title": title, "body": body}
        if labels is not None:
            payload["labels"] = labels
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/issues",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected issue create response")
        return {"repository": repository, "issue": self._compact_issue(result)}

    def update_issue(
        self,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        payload: dict[str, object] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            if state not in {"open", "closed"}:
                raise GitHubAgentError("state must be open or closed")
            payload["state"] = state
        if labels is not None:
            payload["labels"] = labels
        if not payload:
            raise GitHubAgentError("no issue fields were supplied")
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/issues/{number}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected issue update response")
        return {"repository": repository, "issue": self._compact_issue(result)}

    def add_issue_comment(
        self,
        repository: str,
        number: int,
        body: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            payload={"body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected issue comment response")
        return {
            "repository": repository,
            "number": number,
            "comment_id": int(result.get("id", 0)),
            "html_url": str(result.get("html_url", "")),
        }

    def list_workflow_runs(
        self,
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        params: dict[str, str | int] = {
            "per_page": max(1, min(per_page, 100)),
            "page": max(1, page),
        }
        if branch:
            params["branch"] = branch
        if status:
            params["status"] = status
        query = urllib.parse.urlencode(params)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/actions/runs?{query}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected workflow-run response")
        raw = result.get("workflow_runs") if isinstance(result.get("workflow_runs"), list) else []
        runs = [
            {
                "id": int(item.get("id", 0)),
                "name": str(item.get("name", "")),
                "head_branch": str(item.get("head_branch", "")),
                "head_sha": str(item.get("head_sha", "")),
                "status": str(item.get("status", "")),
                "conclusion": item.get("conclusion"),
                "event": str(item.get("event", "")),
                "html_url": str(item.get("html_url", "")),
            }
            for item in raw
            if isinstance(item, dict)
        ]
        return {"repository": repository, "workflow_runs": runs, "page": page}

    def list_workflow_jobs(self, repository: str, run_id: int) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected workflow-job response")
        raw = result.get("jobs") if isinstance(result.get("jobs"), list) else []
        jobs = [
            {
                "id": int(item.get("id", 0)),
                "name": str(item.get("name", "")),
                "status": str(item.get("status", "")),
                "conclusion": item.get("conclusion"),
                "html_url": str(item.get("html_url", "")),
            }
            for item in raw
            if isinstance(item, dict)
        ]
        return {"repository": repository, "run_id": run_id, "jobs": jobs}
