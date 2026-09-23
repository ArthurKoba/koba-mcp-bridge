from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .gitlab_client import GitLabClient


def register_gitlab_pipeline_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab list pipelines", annotations=read_annotations)
    def list_pipelines(
        profile_id: str,
        project: str,
        ref: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List project pipelines."""
        return client_factory(profile_id).list_pipelines(project, ref, status, page, per_page)

    @mcp.tool(title="GitLab pipeline jobs", annotations=read_annotations)
    def list_pipeline_jobs(
        profile_id: str,
        project: str,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List jobs for one pipeline."""
        return client_factory(profile_id).list_pipeline_jobs(
            project, pipeline_id, page, per_page
        )

    @mcp.tool(title="GitLab job trace", annotations=read_annotations)
    def job_trace(
        profile_id: str,
        project: str,
        job_id: int,
        max_chars: int = 100_000,
    ) -> JsonObject:
        """Return the tail of one GitLab CI job trace."""
        return client_factory(profile_id).job_trace(project, job_id, max_chars)

    @mcp.tool(title="GitLab retry pipeline", annotations=write_annotations)
    def retry_pipeline(
        profile_id: str,
        project: str,
        pipeline_id: int,
    ) -> JsonObject:
        """Retry failed/canceled jobs in a pipeline according to GitLab semantics."""
        return client_factory(profile_id).retry_pipeline(project, pipeline_id)

    @mcp.tool(title="GitLab cancel pipeline", annotations=destructive_annotations)
    def cancel_pipeline(
        profile_id: str,
        project: str,
        pipeline_id: int,
    ) -> JsonObject:
        """Cancel a running GitLab pipeline."""
        return client_factory(profile_id).cancel_pipeline(project, pipeline_id)
