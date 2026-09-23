from __future__ import annotations

from common.models import JsonObject

from .api import GitLabApiClient
from .errors import GitLabError


class GitLabIssueClient(GitLabApiClient):
    def list_issues(
        self,
        project: str | int,
        state: str = "opened",
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/issues",
            query={
                "state": state or None,
                "search": search or None,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab issue list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issues": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_issue(self, project: str | int, iid: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request("GET", f"/projects/{selector}/issues/{iid}").data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issue": data,
        }

    def create_issue(
        self,
        project: str | int,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
    ) -> JsonObject:
        selector = self.project_selector(project)
        payload: JsonObject = {"title": title, "description": description}
        if labels:
            payload["labels"] = ",".join(labels)
        data = self.request(
            "POST",
            f"/projects/{selector}/issues",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issue": data,
        }

    def update_issue(
        self,
        project: str | int,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        labels: list[str] | None = None,
    ) -> JsonObject:
        selector = self.project_selector(project)
        payload: JsonObject = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if state_event is not None:
            payload["state_event"] = state_event
        if labels is not None:
            payload["labels"] = ",".join(labels)
        if not payload:
            raise GitLabError("at least one issue field must be supplied")
        data = self.request(
            "PUT",
            f"/projects/{selector}/issues/{iid}",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issue": data,
        }

    def add_issue_note(
        self,
        project: str | int,
        iid: int,
        body: str,
    ) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/issues/{iid}/notes",
            payload={"body": body},
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "note": data,
        }
