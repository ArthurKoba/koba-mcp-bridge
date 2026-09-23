from __future__ import annotations

from common.models import JsonObject

from .api import GitLabApiClient
from .errors import GitLabError


class GitLabProjectClient(GitLabApiClient):
    def profile_status(self) -> JsonObject:
        user = self.request("GET", "/user").data
        version = self.request("GET", "/version", allowed_errors={401, 403, 404}).data
        if not isinstance(user, dict):
            raise GitLabError("unexpected GitLab /user response")
        return {
            "account": self.profile.public(),
            "authenticated_user": {
                "id": user.get("id"),
                "username": user.get("username"),
                "name": user.get("name"),
                "state": user.get("state"),
                "web_url": user.get("web_url"),
            },
            "gitlab_version": version if isinstance(version, dict) else {},
            "status": "ok",
        }

    def list_projects(
        self,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        if page <= 0 or per_page <= 0 or per_page > 100:
            raise GitLabError("page must be > 0 and per_page must be between 1 and 100")
        query: JsonObject = {
            "membership": membership,
            "owned": owned,
            "simple": True,
            "page": page,
            "per_page": per_page,
            "order_by": "path",
            "sort": "asc",
        }
        if search.strip():
            query["search"] = search.strip()
        if min_access_level:
            query["min_access_level"] = min_access_level
        response = self.request("GET", "/projects", query=query)
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab project list response")
        return {
            "account_id": self.profile.account_id,
            "projects": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
            "total": _header_int(response.headers, "X-Total"),
            "total_pages": _header_int(response.headers, "X-Total-Pages"),
        }

    def project_status(self, project: str | int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request("GET", f"/projects/{selector}").data
        if not isinstance(data, dict):
            raise GitLabError("unexpected GitLab project response")
        return {"account_id": self.profile.account_id, "project": data}


def _header_int(headers: dict[str, str], name: str) -> int | None:
    raw = headers.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
