from __future__ import annotations

import base64
import urllib.parse

from common.models import JsonObject, json_object

from .api import GitLabApiClient
from .errors import GitLabError
from .models import GitLabCommitAction
from .policy import require_mutable_branch


class GitLabRepositoryClient(GitLabApiClient):
    def get_file(self, project: str | int, path: str, ref: str = "main") -> JsonObject:
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": ref},
        )
        data = response.data
        if not isinstance(data, dict):
            raise GitLabError("unexpected GitLab repository file response")
        encoding = str(data.get("encoding", ""))
        content = str(data.get("content", ""))
        if encoding != "base64":
            raise GitLabError(f"unsupported GitLab repository file encoding: {encoding}")
        decoded = base64.b64decode(content).decode("utf-8", "replace")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": data.get("file_path", path),
            "ref": ref,
            "blob_id": data.get("blob_id"),
            "commit_id": data.get("commit_id"),
            "last_commit_id": data.get("last_commit_id"),
            "size": data.get("size"),
            "content": decoded,
        }

    def list_tree(
        self,
        project: str | int,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/tree",
            query={
                "path": path or None,
                "ref": ref,
                "recursive": recursive,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab repository tree response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "items": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def search_code(
        self,
        project: str | int,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        query: JsonObject = {
            "scope": "blobs",
            "search": search,
            "page": page,
            "per_page": per_page,
        }
        if ref:
            query["ref"] = ref
        response = self.request("GET", f"/projects/{selector}/search", query=query)
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab code search response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "results": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def put_file(
        self,
        project: str | int,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        existing = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": branch},
            allowed_errors={404},
        )
        method = "POST" if existing.status == 404 else "PUT"
        payload: JsonObject = {
            "branch": branch,
            "content": content,
            "commit_message": commit_message,
        }
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            method,
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "operation": "create" if method == "POST" else "update",
            "result": response.data,
        }

    def delete_file(
        self,
        project: str | int,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        payload: JsonObject = {
            "branch": branch,
            "commit_message": commit_message,
        }
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "result": response.data,
        }

    def commit_actions(
        self,
        project: str | int,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        if not actions:
            raise GitLabError("actions must not be empty")
        clean_actions = [action.to_json() for action in actions]
        selector = self.project_selector(project)
        payload = json_object(
            {
                "branch": branch,
                "commit_message": commit_message,
                "actions": clean_actions,
            },
            context="GitLab commit payload",
        )
        if start_branch:
            payload["start_branch"] = start_branch
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/commits",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "commit": response.data,
        }

    def list_branches(
        self,
        project: str | int,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/branches",
            query={"search": search or None, "page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab branch list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branches": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def create_branch(
        self,
        project: str | int,
        branch: str,
        ref: str,
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/branches",
            query={"branch": branch, "ref": ref},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": response.data,
        }

    def delete_branch(self, project: str | int, branch: str) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        branch_q = urllib.parse.quote(branch, safe="")
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/branches/{branch_q}",
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "status": response.status,
            "deleted": True,
        }

    def compare(
        self,
        project: str | int,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/compare",
            query={"from": from_ref, "to": to_ref, "straight": straight},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "comparison": response.data,
        }
