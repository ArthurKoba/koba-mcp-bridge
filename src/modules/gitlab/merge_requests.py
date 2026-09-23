from __future__ import annotations

from common.models import JsonObject

from .api import GitLabApiClient
from .errors import GitLabError


class GitLabMergeRequestClient(GitLabApiClient):
    def list_merge_requests(
        self,
        project: str | int,
        state: str = "opened",
        source_branch: str = "",
        target_branch: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/merge_requests",
            query={
                "state": state or None,
                "source_branch": source_branch or None,
                "target_branch": target_branch or None,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab merge request list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_requests": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_merge_request(self, project: str | int, iid: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request(
            "GET",
            f"/projects/{selector}/merge_requests/{iid}",
            query={"include_diverged_commits_count": True, "include_rebase_in_progress": True},
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def create_merge_request(
        self,
        project: str | int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        remove_source_branch: bool = False,
        squash: bool = False,
        draft: bool = False,
    ) -> JsonObject:
        selector = self.project_selector(project)
        mr_title = title
        if draft and not title.lower().startswith(("draft:", "wip:")):
            mr_title = f"Draft: {title}"
        payload = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": mr_title,
            "description": description,
            "remove_source_branch": remove_source_branch,
            "squash": squash,
        }
        data = self.request(
            "POST",
            f"/projects/{selector}/merge_requests",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def update_merge_request(
        self,
        project: str | int,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        target_branch: str | None = None,
        remove_source_branch: bool | None = None,
        squash: bool | None = None,
    ) -> JsonObject:
        selector = self.project_selector(project)
        payload: JsonObject = {}
        for key, value in {
            "title": title,
            "description": description,
            "state_event": state_event,
            "target_branch": target_branch,
            "remove_source_branch": remove_source_branch,
            "squash": squash,
        }.items():
            if value is not None:
                payload[key] = value
        if not payload:
            raise GitLabError("at least one merge request field must be supplied")
        data = self.request(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def merge_merge_request(
        self,
        project: str | int,
        iid: int,
        sha: str = "",
        squash: bool | None = None,
        should_remove_source_branch: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> JsonObject:
        selector = self.project_selector(project)
        payload: JsonObject = {
            "merge_when_pipeline_succeeds": merge_when_pipeline_succeeds,
        }
        if sha:
            payload["sha"] = sha
        if squash is not None:
            payload["squash"] = squash
        if should_remove_source_branch is not None:
            payload["should_remove_source_branch"] = should_remove_source_branch
        if merge_commit_message:
            payload["merge_commit_message"] = merge_commit_message
        if squash_commit_message:
            payload["squash_commit_message"] = squash_commit_message
        data = self.request(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}/merge",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }
