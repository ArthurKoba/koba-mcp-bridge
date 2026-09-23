from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from common.models import JsonObject, JsonValue, json_array, json_int, json_str

from .git_transaction import GitHubGitDataTransactionClient
from .github_agent import GitHubAgentError
from .models import AtomicChange, CopySpec


class GitHubGitMutationClient(GitHubGitDataTransactionClient):
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
        source_ref = source_ref.strip()
        operation = operation.strip().casefold()
        if not source_ref:
            raise GitHubAgentError("source_ref must not be empty")
        if not copies:
            raise GitHubAgentError("copies must not be empty")
        try:
            normalized_copies = [
                item if isinstance(item, CopySpec) else CopySpec.model_validate(item)
                for item in copies
            ]
        except ValidationError as exc:
            raise GitHubAgentError("invalid copy specification") from exc
        if operation not in {"copy", "move"}:
            raise GitHubAgentError("operation must be 'copy' or 'move'")

        source_sha = self._resolve_commit_sha(repository, source_ref)
        transaction = self._begin_git_transaction(
            repository,
            branch,
            expected_head_sha,
        )
        if operation == "move" and source_sha != transaction.head_sha:
            raise GitHubAgentError(
                "move requires source_ref to resolve to the current destination branch HEAD"
            )

        source_tree = transaction.base_tree_sha
        if source_sha != transaction.head_sha:
            source_tree = self._resolve_commit_tree(repository, source_sha)

        tree_entries: list[JsonObject] = []
        seen_destinations: set[str] = set()
        seen_move_sources: set[str] = set()
        processed: list[JsonObject] = []

        for item in normalized_copies:
            source_path = "/".join(
                part for part in item.source_path.strip("/").split("/") if part
            )
            destination_path = "/".join(
                part for part in item.destination_path.strip("/").split("/") if part
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
                raise GitHubAgentError(f"duplicate destination_path: {destination_path}")
            seen_destinations.add(destination_path)
            if operation == "move":
                if source_path in seen_move_sources:
                    raise GitHubAgentError(f"duplicate move source_path: {source_path}")
                seen_move_sources.add(source_path)

            source = self._tree_entry_at_path(repository, source_tree, source_path)
            if source is None or json_str(source.get("type")) != "blob":
                raise GitHubAgentError(f"source path is not a Git blob: {source_path}")
            blob_sha = json_str(source.get("sha"))
            source_mode = json_str(source.get("mode"))
            if not blob_sha or not source_mode:
                raise GitHubAgentError(
                    f"source blob is missing sha or mode: {source_path}"
                )
            mode = item.mode or source_mode

            destination = self._tree_entry_at_path(
                repository,
                transaction.base_tree_sha,
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

        committed = self._commit_tree_entries(transaction, message, tree_entries)
        return {
            "repository": repository,
            "source_ref": source_ref,
            "source_sha": source_sha,
            "branch": transaction.branch,
            "operation": operation,
            "previous_head_sha": committed.previous_head_sha,
            "commit_sha": committed.commit_sha,
            "tree_sha": committed.tree_sha,
            "copied": json_array(
                processed if operation == "copy" else [],
                context="GitHub copied files",
            ),
            "moved": json_array(
                processed if operation == "move" else [],
                context="GitHub moved files",
            ),
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

        transaction = self._begin_git_transaction(
            repository,
            branch,
            expected_head_sha,
        )
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
                    source_sha = self._resolve_commit_sha(repository, source_ref)
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

            encoded = change.content_base64
            blob_payload: JsonObject
            if encoded is not None:
                blob_payload = {"content": str(encoded), "encoding": "base64"}
            else:
                blob_payload = {"content": str(change.content), "encoding": "utf-8"}
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

        committed = self._commit_tree_entries(transaction, message, tree_entries)
        return {
            "repository": repository,
            "branch": transaction.branch,
            "previous_head_sha": committed.previous_head_sha,
            "commit_sha": committed.commit_sha,
            "tree_sha": committed.tree_sha,
            "changed_paths": [change.path for change in normalized_changes],
        }
