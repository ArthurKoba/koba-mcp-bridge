from __future__ import annotations

from common.models import JsonObject

from .api import GitLabApiClient
from .errors import GitLabError


class GitLabPipelineClient(GitLabApiClient):
    def list_pipelines(
        self,
        project: str | int,
        ref: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/pipelines",
            query={
                "ref": ref or None,
                "status": status or None,
                "page": page,
                "per_page": per_page,
                "order_by": "id",
                "sort": "desc",
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab pipeline list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipelines": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def list_pipeline_jobs(
        self,
        project: str | int,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/pipelines/{pipeline_id}/jobs",
            query={"page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab pipeline jobs response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline_id": pipeline_id,
            "jobs": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def job_trace(
        self,
        project: str | int,
        job_id: int,
        max_chars: int = 100_000,
    ) -> JsonObject:
        if max_chars <= 0 or max_chars > 2_000_000:
            raise GitLabError("max_chars must be between 1 and 2000000")
        selector = self.project_selector(project)
        response = self.request_text(
            "GET",
            f"/projects/{selector}/jobs/{job_id}/trace",
        )
        trace = str(response.data)
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "job_id": job_id,
            "truncated": len(trace) > max_chars,
            "trace_tail": trace[-max_chars:],
        }

    def retry_pipeline(self, project: str | int, pipeline_id: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/retry",
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline": data,
        }

    def cancel_pipeline(self, project: str | int, pipeline_id: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/cancel",
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline": data,
        }
