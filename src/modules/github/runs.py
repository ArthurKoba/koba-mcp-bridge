from __future__ import annotations

from common.models import (
    JsonObject,
    json_array,
    json_int,
    json_member_array,
    json_str,
)

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError


class GitHubRunClient(GitHubRepositoryClientBase):
    def list_workflow_runs(
        self,
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> JsonObject:
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
        raw = json_member_array(result, "workflow_runs")
        runs = [
            {
                "id": json_int(item.get("id")),
                "name": json_str(item.get("name")),
                "head_branch": json_str(item.get("head_branch")),
                "head_sha": json_str(item.get("head_sha")),
                "status": json_str(item.get("status")),
                "conclusion": item.get("conclusion"),
                "event": json_str(item.get("event")),
                "html_url": json_str(item.get("html_url")),
            }
            for item in raw
            if isinstance(item, dict)
        ]
        return {
            "repository": repository,
            "workflow_runs": json_array(runs, context="GitHub workflow runs"),
            "page": page,
        }

    def list_workflow_jobs(self, repository: str, run_id: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected workflow-job response")
        raw = json_member_array(result, "jobs")
        jobs = [
            {
                "id": json_int(item.get("id")),
                "name": json_str(item.get("name")),
                "status": json_str(item.get("status")),
                "conclusion": item.get("conclusion"),
                "html_url": json_str(item.get("html_url")),
            }
            for item in raw
            if isinstance(item, dict)
        ]
        return {
            "repository": repository,
            "run_id": run_id,
            "jobs": json_array(jobs, context="GitHub workflow jobs"),
        }
