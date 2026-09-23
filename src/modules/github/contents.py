from __future__ import annotations

import base64
import urllib.parse
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from common.models import (
    JsonObject,
    JsonValue,
    json_array,
    json_int,
    json_member_array,
    json_member_object,
    json_object,
    json_str,
)

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError
from .models import AtomicChange, CopySpec


class GitHubContentsClient(GitHubRepositoryClientBase):
    def list_directory(
        self,
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> JsonObject:
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
                "name": json_str(item.get("name")),
                "path": json_str(item.get("path")),
                "type": json_str(item.get("type")),
                "size": json_int(item.get("size")),
                "sha": json_str(item.get("sha")),
            }
            for item in result
            if isinstance(item, dict)
        ]
        return {
            "repository": repository,
            "path": path,
            "ref": ref,
            "entries": json_array(entries, context="GitHub directory entries"),
        }

    def get_file(self, repository: str, path: str, ref: str | None = None) -> JsonObject:
        repository = self._assert_allowed(repository)
        quoted_path = self._path(path)
        query = ""
        if ref:
            query = "?ref=" + self._quote(ref)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{quoted_path}{query}",
        )
        try:
            payload = json_object(result, context="GitHub file response")
            if json_str(payload.get("type")) != "file":
                raise ValueError("not a file")
            encoding = json_str(payload.get("encoding"))
            content = json_str(payload.get("content"))
        except ValueError as exc:
            raise GitHubAgentError(
                "path is not a regular GitHub repository file"
            ) from exc
        if encoding != "base64":
            raise GitHubAgentError(f"unsupported GitHub content encoding: {encoding}")
        decoded = base64.b64decode(content).decode("utf-8", "replace")
        return {
            "repository": repository,
            "path": json_str(payload.get("path"), default=path),
            "sha": json_str(payload.get("sha")),
            "size": json_int(payload.get("size")),
            "content": decoded,
        }

    def get_binary_file(
        self,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        endpoint = f"/repos/{repository}/contents/{self._path(path)}"
        if ref:
            endpoint += "?ref=" + self._quote(ref)
        _, result = self._repo_request(repository, "GET", endpoint)
        if not isinstance(result, dict) or result.get("type") != "file":
            raise GitHubAgentError("path is not a regular file")
        if json_str(result.get("encoding")) != "base64":
            raise GitHubAgentError("GitHub did not return base64 file content")
        return {
            "repository": repository,
            "path": json_str(result.get("path"), default=path),
            "sha": json_str(result.get("sha")),
            "size": json_int(result.get("size")),
            "content_base64": json_str(result.get("content")).replace("\n", ""),
        }

    def put_file(
        self,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        quoted_path = self._path(path)
        ref = self._quote(branch)
        status, current = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{quoted_path}?ref={ref}",
            allowed_errors={404},
        )
        payload: JsonObject = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        operation = "create"
        if status != 404:
            try:
                current_payload = json_object(
                    current,
                    context="GitHub existing file response",
                )
                if json_str(current_payload.get("type")) != "file":
                    raise ValueError("not a file")
                payload["sha"] = json_str(current_payload.get("sha"))
            except ValueError as exc:
                raise GitHubAgentError(
                    "existing path is not a regular file"
                ) from exc
            operation = "update"

        response_status, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/contents/{quoted_path}",
            payload=payload,
        )
        try:
            write_payload = json_object(
                result,
                context="GitHub file write response",
            )
            commit = json_member_object(write_payload, "commit")
            saved = json_member_object(write_payload, "content")
        except ValueError as exc:
            raise GitHubAgentError("unexpected file write response") from exc
        return {
            "status": response_status,
            "operation": operation,
            "repository": repository,
            "branch": branch,
            "path": path,
            "commit_sha": json_str(commit.get("sha")),
            "content_sha": json_str(saved.get("sha")),
        }

    def put_binary_file(
        self,
        repository: str,
        path: str,
        content_base64: str,
        message: str,
        branch: str,
    ) -> JsonObject:
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
        payload: JsonObject = {
            "message": message,
            "content": content_base64,
            "branch": branch,
        }
        operation = "create"
        if status != 404:
            if not isinstance(current, dict) or current.get("type") != "file":
                raise GitHubAgentError("existing path is not a regular file")
            payload["sha"] = json_str(current.get("sha"))
            operation = "update"
        response_status, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/contents/{quoted_path}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected binary file write response")
        commit = json_member_object(result, "commit")
        saved = json_member_object(result, "content")
        return {
            "status": response_status,
            "operation": operation,
            "repository": repository,
            "branch": branch,
            "path": path,
            "commit_sha": json_str(commit.get("sha")),
            "content_sha": json_str(saved.get("sha")),
        }

    def _tree_entry_at_path(
        self,
        repository: str,
        root_tree_sha: str,
        path: str,
    ) -> JsonObject | None:
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
            if not isinstance(tree, dict):
                raise GitHubAgentError("unexpected Git tree response")
            try:
                tree_items = json_member_array(tree, "tree", required=True)
            except ValueError as exc:
                raise GitHubAgentError("unexpected Git tree response") from exc
            entry = next(
                (
                    item
                    for item in tree_items
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

    def copy_files(
        self,
        repository: str,
        source_ref: str,
        branch: str,
        message: str,
        copies: Sequence[CopySpec | Mapping[str, JsonValue]],
        expected_head_sha: str | None = None,
        operation: str = "copy",
        overwrite: bool = False,
    ) -> JsonObject:
        """Copy or move existing Git blobs without transferring file contents."""
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        source_ref = source_ref.strip()
        operation = operation.strip().casefold()
        if not source_ref:
            raise GitHubAgentError("source_ref must not be empty")
        if not copies:
            raise GitHubAgentError("copies must not be empty")
        try:
            normalized_copies = [
                item
                if isinstance(item, CopySpec)
                else CopySpec.model_validate(item)
                for item in copies
            ]
        except ValidationError as exc:
            raise GitHubAgentError("invalid copy specification") from exc
        if operation not in {"copy", "move"}:
            raise GitHubAgentError("operation must be 'copy' or 'move'")

        _, source_commit = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(source_ref)}",
        )
        if not isinstance(source_commit, dict):
            raise GitHubAgentError("unable to resolve source_ref")
        source_sha = json_str(source_commit.get("sha"))
        if not source_sha:
            raise GitHubAgentError("unable to resolve source_ref")

        branch_q = self._quote(branch)
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
            raise GitHubAgentError("unable to resolve branch head")
        head_sha = json_str(json_member_object(ref, "object", required=True).get("sha"))
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
        base_tree = json_str(json_member_object(parent, "tree", required=True).get("sha"))
        if not base_tree:
            raise GitHubAgentError("parent commit has no tree sha")

        source_tree = base_tree
        if source_sha != head_sha:
            _, source_git_commit = self._repo_request(
                repository,
                "GET",
                f"/repos/{repository}/git/commits/{source_sha}",
            )
            if not isinstance(source_git_commit, dict):
                raise GitHubAgentError("unable to resolve source commit tree")
            source_tree = json_str(
                json_member_object(
                    source_git_commit,
                    "tree",
                    required=True,
                ).get("sha")
            )
            if not source_tree:
                raise GitHubAgentError("source commit has no tree sha")

        tree_entries: list[JsonObject] = []
        seen_destinations: set[str] = set()
        seen_move_sources: set[str] = set()
        processed: list[JsonObject] = []

        for item in normalized_copies:
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
            if source is None or json_str(source.get("type")) != "blob":
                raise GitHubAgentError(
                    f"source path is not a Git blob: {source_path}"
                )
            blob_sha = json_str(source.get("sha"))
            source_mode = json_str(source.get("mode"))
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
                if json_str(destination.get("type")) != "blob":
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
                    "size": json_int(source.get("size")),
                }
            )

        _, tree = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/trees",
            payload={"base_tree": base_tree, "tree": tree_entries},
        )
        if not isinstance(tree, dict):
            raise GitHubAgentError("GitHub did not return a tree sha")
        tree_sha = json_str(tree.get("sha"))
        if not tree_sha:
            raise GitHubAgentError("GitHub did not return a tree sha")

        _, new_commit = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/commits",
            payload={"message": message, "tree": tree_sha, "parents": [head_sha]},
        )
        if not isinstance(new_commit, dict):
            raise GitHubAgentError("GitHub did not return a commit sha")
        commit_sha = json_str(new_commit.get("sha"))
        if not commit_sha:
            raise GitHubAgentError("GitHub did not return a commit sha")

        _, current_ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        current_object = (
            json_member_object(current_ref, "object")
            if isinstance(current_ref, dict)
            else {}
        )
        current_head_sha = json_str(current_object.get("sha"))
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
            "copied": json_array(
                processed if operation == "copy" else [],
                context="GitHub copied files",
            ),
            "moved": json_array(
                processed if operation == "move" else [],
                context="GitHub moved files",
            ),
        }

    def delete_file(
        self,
        repository: str,
        path: str,
        message: str,
        branch: str,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        quoted_path = self._path(path)
        ref = self._quote(branch)
        _, current = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{quoted_path}?ref={ref}",
        )
        try:
            current_payload = json_object(
                current,
                context="GitHub file delete source",
            )
            if json_str(current_payload.get("type")) != "file":
                raise ValueError("not a file")
            sha = json_str(current_payload.get("sha"))
        except ValueError as exc:
            raise GitHubAgentError("path is not a regular file") from exc
        _, result = self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/contents/{quoted_path}",
            payload={"message": message, "sha": sha, "branch": branch},
        )
        try:
            delete_payload = json_object(
                result,
                context="GitHub file delete response",
            )
            commit = json_member_object(delete_payload, "commit")
        except ValueError as exc:
            raise GitHubAgentError("unexpected file delete response") from exc
        return {
            "repository": repository,
            "branch": branch,
            "path": path,
            "commit_sha": str(commit.get("sha", "")),
        }

    def commit_files(
        self,
        repository: str,
        branch: str,
        message: str,
        changes: Sequence[AtomicChange | Mapping[str, JsonValue]],
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        if not changes:
            raise GitHubAgentError("changes must not be empty")
        try:
            normalized_changes = [
                item
                if isinstance(item, AtomicChange)
                else AtomicChange.model_validate(item)
                for item in changes
            ]
        except ValidationError as exc:
            raise GitHubAgentError("invalid atomic change") from exc

        branch_q = self._quote(branch)
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
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

        _, parent = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{head_sha}",
        )
        if not isinstance(parent, dict):
            raise GitHubAgentError("unable to resolve parent tree")
        base_tree = json_str(
            json_member_object(parent, "tree", required=True).get("sha")
        )
        if not base_tree:
            raise GitHubAgentError("parent commit has no tree sha")

        tree_entries: list[JsonObject] = []
        copy_ref_cache: dict[str, str] = {}
        for change in normalized_changes:
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
                    if not isinstance(source_commit, dict):
                        raise GitHubAgentError(
                            f"unable to resolve source_ref: {source_ref}"
                        )
                    source_sha = json_str(source_commit.get("sha"))
                    if not source_sha:
                        raise GitHubAgentError(
                            f"unable to resolve source_ref: {source_ref}"
                        )
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
                blob_sha = json_str(source.get("sha"))
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
            if not isinstance(blob, dict):
                raise GitHubAgentError("GitHub did not return a blob sha")
            blob_sha = json_str(blob.get("sha"))
            if not blob_sha:
                raise GitHubAgentError("GitHub did not return a blob sha")
            tree_entries.append(
                {
                    "path": path,
                    "mode": mode,
                    "type": "blob",
                    "sha": blob_sha,
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
        if not isinstance(commit, dict):
            raise GitHubAgentError("GitHub did not return a commit sha")
        commit_sha = json_str(commit.get("sha"))
        if not commit_sha:
            raise GitHubAgentError("GitHub did not return a commit sha")

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
            "changed_paths": [change.path for change in normalized_changes],
        }

    def search_code(
        self,
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> JsonObject:
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
        items = json_member_array(result, "items")
        return {
            "repository": repository,
            "total_count": json_int(result.get("total_count")),
            "items": [
                {
                    "name": json_str(item.get("name")),
                    "path": json_str(item.get("path")),
                    "sha": json_str(item.get("sha")),
                }
                for item in items
                if isinstance(item, dict)
            ],
            "page": page,
        }
