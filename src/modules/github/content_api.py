from __future__ import annotations

import base64
import urllib.parse

from common.models import (
    JsonObject,
    json_array,
    json_int,
    json_member_array,
    json_member_object,
    json_object,
    json_str,
)

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError


class GitHubContentApiClient(GitHubRepositoryClientBase):
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
