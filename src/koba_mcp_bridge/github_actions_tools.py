from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_actions import GitHubActionsClient


def register_github_actions_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    """Register CI diagnostics plus controlled Actions rerun/cancel tools."""

    @mcp.tool(title="GitHub agent workflow job log", annotations=read_annotations)
    def github_agent_workflow_job_log(
        repository: str,
        job_id: int,
        max_chars: int = 100_000,
    ) -> dict[str, object]:
        """Download and return the tail of one GitHub Actions job log."""
        return client_factory().get_workflow_job_log(repository, job_id, max_chars)

    @mcp.tool(title="GitHub agent workflow artifacts", annotations=read_annotations)
    def github_agent_workflow_artifacts(
        repository: str,
        run_id: int,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, object]:
        """List artifacts produced by one workflow run."""
        return client_factory().list_workflow_artifacts(
            repository,
            run_id,
            per_page,
            page,
        )

    @mcp.tool(title="GitHub agent download workflow artifact", annotations=read_annotations)
    def github_agent_download_workflow_artifact(
        repository: str,
        artifact_id: int,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> dict[str, object]:
        """Download a small workflow artifact ZIP as base64 with SHA-256."""
        return client_factory().download_workflow_artifact(
            repository,
            artifact_id,
            max_bytes,
        )

    @mcp.tool(title="GitHub agent rerun workflow job", annotations=write_annotations)
    def github_agent_rerun_workflow_job(
        repository: str,
        job_id: int,
    ) -> dict[str, object]:
        """Re-run one GitHub Actions job."""
        return client_factory().rerun_workflow_job(repository, job_id)

    @mcp.tool(title="GitHub agent rerun failed workflow jobs", annotations=write_annotations)
    def github_agent_rerun_failed_workflow_jobs(
        repository: str,
        run_id: int,
    ) -> dict[str, object]:
        """Re-run only failed jobs in one workflow run."""
        return client_factory().rerun_failed_workflow_jobs(repository, run_id)

    @mcp.tool(title="GitHub agent rerun workflow run", annotations=write_annotations)
    def github_agent_rerun_workflow_run(
        repository: str,
        run_id: int,
    ) -> dict[str, object]:
        """Re-run every job in one workflow run."""
        return client_factory().rerun_workflow_run(repository, run_id)

    @mcp.tool(title="GitHub agent cancel workflow run", annotations=destructive_annotations)
    def github_agent_cancel_workflow_run(
        repository: str,
        run_id: int,
    ) -> dict[str, object]:
        """Cancel an in-progress GitHub Actions workflow run."""
        return client_factory().cancel_workflow_run(repository, run_id)
