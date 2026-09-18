from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_actions import GitHubActionsClient
from .github_admin import repoint_reserved_branch
from .github_history_graph import rewrite_branch_identity_graph
from .github_reviewer import github_reviewer_client_from_env, github_reviewer_configured


def register_github_actions_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    """Register GitHub capability/history controls plus Actions diagnostics."""

    @mcp.tool(title="GitHub agent capabilities", annotations=read_annotations)
    def github_agent_capabilities(repository: str) -> dict[str, object]:
        """Inspect effective GitHub App permissions, identity, and bridge policy."""
        return client_factory().capabilities(
            repository,
            reviewer_available=github_reviewer_configured(),
        )

    @mcp.tool(
        title="GitHub agent rewrite branch identity",
        annotations=destructive_annotations,
    )
    def github_agent_rewrite_branch_identity(
        repository: str,
        branch: str,
        expected_head_sha: str,
        identity_source: str = "current_agent_app",
        preserve_messages: bool = True,
        preserve_trees: bool = True,
        preserve_author_dates: bool = True,
        base_sha: str | None = None,
        max_commits: int = 100,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Rewrite linear branch history to the current Agent App Git identity.

        The operation is identity-only: messages and trees must be preserved. It
        requires an expected branch head, supports an exclusive base_sha boundary,
        validates every rewritten tree and the final tree, re-checks the branch
        head immediately before the single forced ref update, and defaults to dry-run.
        """
        return client_factory().rewrite_branch_identity(
            repository,
            branch,
            expected_head_sha,
            identity_source=identity_source,
            preserve_messages=preserve_messages,
            preserve_trees=preserve_trees,
            preserve_author_dates=preserve_author_dates,
            base_sha=base_sha,
            max_commits=max_commits,
            dry_run=dry_run,
        )

    @mcp.tool(
        title="GitHub agent rewrite branch identity graph",
        annotations=destructive_annotations,
    )
    def github_agent_rewrite_branch_identity_graph(
        repository: str,
        branch: str,
        expected_head_sha: str,
        identity_source: str = "current_agent_app",
        preserve_messages: bool = True,
        preserve_trees: bool = True,
        preserve_author_dates: bool = True,
        max_commits: int = 500,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Rewrite a reachable merge DAG to the current Agent App Git identity.

        Parent ordering/topology, commit trees, messages, and optional original Git
        dates are preserved. The operation requires an expected branch head, validates
        the reconstructed DAG and final tree, performs one CAS-style head re-check,
        and only then force-replaces the branch ref. Dry-run creates unreachable Git
        commit objects so the returned old->new mapping is exact.
        """
        return rewrite_branch_identity_graph(
            client_factory(),
            repository,
            branch,
            expected_head_sha,
            identity_source=identity_source,
            preserve_messages=preserve_messages,
            preserve_trees=preserve_trees,
            preserve_author_dates=preserve_author_dates,
            max_commits=max_commits,
            dry_run=dry_run,
        )

    @mcp.tool(
        title="GitHub admin repoint reserved branch",
        annotations=destructive_annotations,
    )
    def github_admin_repoint_reserved_branch(
        repository: str,
        branch: str,
        expected_head_sha: str,
        target_sha: str,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Repoint a Bridge-reserved branch without changing its repository tree.

        This is a narrow maintenance primitive, not a general force-ref operation.
        The target commit must have the same tree as the current reserved branch,
        must already use the current Agent App identity, and the branch must not be
        the repository default branch or GitHub-protected. The operation requires an
        expected head SHA, re-checks it immediately before the forced ref update, and
        defaults to dry-run.
        """
        return repoint_reserved_branch(
            client_factory(),
            repository,
            branch,
            expected_head_sha,
            target_sha,
            dry_run=dry_run,
        )

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
        """List artifacts produced by one GitHub Actions workflow run."""
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

    @mcp.tool(title="GitHub agent dispatch workflow", annotations=write_annotations)
    def github_agent_dispatch_workflow(
        repository: str,
        workflow_id: str,
        ref: str,
        inputs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Dispatch a workflow_dispatch workflow with an explicit ref and inputs."""
        return client_factory().dispatch_workflow(
            repository,
            workflow_id,
            ref,
            inputs,
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

    if github_reviewer_configured():

        @mcp.tool(title="GitHub reviewer workflow job log", annotations=read_annotations)
        def github_reviewer_workflow_job_log(
            repository: str,
            job_id: int,
            max_chars: int = 100_000,
        ) -> dict[str, object]:
            """Read the tail of one Actions job log using reviewer identity."""
            return github_reviewer_client_from_env().get_workflow_job_log(
                repository,
                job_id,
                max_chars,
            )

        @mcp.tool(title="GitHub reviewer workflow artifacts", annotations=read_annotations)
        def github_reviewer_workflow_artifacts(
            repository: str,
            run_id: int,
            per_page: int = 100,
            page: int = 1,
        ) -> dict[str, object]:
            """List workflow artifacts using reviewer identity."""
            return github_reviewer_client_from_env().list_workflow_artifacts(
                repository,
                run_id,
                per_page,
                page,
            )

        @mcp.tool(
            title="GitHub reviewer download workflow artifact",
            annotations=read_annotations,
        )
        def github_reviewer_download_workflow_artifact(
            repository: str,
            artifact_id: int,
            max_bytes: int = 8 * 1024 * 1024,
        ) -> dict[str, object]:
            """Download a small workflow artifact ZIP using reviewer identity."""
            return github_reviewer_client_from_env().download_workflow_artifact(
                repository,
                artifact_id,
                max_bytes,
            )
