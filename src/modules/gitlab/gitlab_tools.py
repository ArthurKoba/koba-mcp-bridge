from __future__ import annotations

import os
import threading
import time

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp.types import ToolAnnotations

from common.models import JsonObject

from .gitlab_client import GitLabClient, GitLabProfileRegistry
from .models import GitLabCommitAction

_registry_lock = threading.Lock()


class _RegistryCacheState:
    def __init__(self) -> None:
        self.value: tuple[float, tuple[str, ...], GitLabProfileRegistry] | None = None


_registry_cache = _RegistryCacheState()
_client_cache: dict[str, GitLabClient] = {}


def _cache_ttl_seconds() -> float:
    raw = os.getenv("GITLAB_REGISTRY_CACHE_TTL_SECONDS", "60").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("GITLAB_REGISTRY_CACHE_TTL_SECONDS must be a number") from exc
    if value < 0 or value > 3600:
        raise RuntimeError(
            "GITLAB_REGISTRY_CACHE_TTL_SECONDS must be between 0 and 3600"
        )
    return value


def _registry_fingerprint() -> tuple[str, ...]:
    return (
        os.getenv("INFISICAL_HOST", ""),
        os.getenv("INFISICAL_PROJECT_ID", ""),
        os.getenv("INFISICAL_ENVIRONMENT", "prod"),
        os.getenv("INFISICAL_BASE_PATH", "/"),
        os.getenv("INFISICAL_CLIENT_ID", ""),
        os.getenv("INFISICAL_CLIENT_ID_FILE", ""),
        os.getenv("INFISICAL_CLIENT_SECRET_FILE", ""),
        os.getenv("INFISICAL_VERIFY_TLS", "true"),
        os.getenv("INFISICAL_CA_FILE", ""),
    )


def _registry() -> GitLabProfileRegistry:
    ttl = _cache_ttl_seconds()
    fingerprint = _registry_fingerprint()
    now = time.monotonic()

    with _registry_lock:
        cached = _registry_cache.value
        if (
            ttl > 0
            and cached is not None
            and cached[0] > now
            and cached[1] == fingerprint
        ):
            return cached[2]

        registry = GitLabProfileRegistry.from_infisical()
        _registry_cache.value = (now + ttl, fingerprint, registry)
        return registry


def _client(profile_id: str) -> GitLabClient:
    profile = _registry().get(profile_id)
    key = profile.profile_id.casefold()

    with _registry_lock:
        cached = _client_cache.get(key)
        if cached is not None and cached.profile == profile:
            return cached
        client = GitLabClient(profile)
        _client_cache[key] = client
        return client


def _clear_runtime_cache() -> None:
    with _registry_lock:
        _registry_cache.value = None
        _client_cache.clear()


def register_gitlab_tools(
    mcp: FastMCP,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab profiles", annotations=read_annotations)
    def profiles() -> JsonObject:
        """List configured GitLab connection/account profiles without exposing tokens."""
        return _registry().list()

    @mcp.tool(title="GitLab profile status", annotations=read_annotations)
    def profile_status(profile_id: str) -> JsonObject:
        """Verify one explicit GitLab profile and report the authenticated account."""
        return _client(profile_id).profile_status()

    @mcp.tool(title="GitLab list projects", annotations=read_annotations)
    def list_projects(
        profile_id: str,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List projects visible to the selected GitLab profile/account."""
        return _client(profile_id).list_projects(
            search, membership, owned, min_access_level, page, per_page
        )

    @mcp.tool(title="GitLab project status", annotations=read_annotations)
    def project_status(profile_id: str, project: str) -> JsonObject:
        """Read project metadata using a numeric project id or path_with_namespace."""
        return _client(profile_id).project_status(project)

    @mcp.tool(title="GitLab get file", annotations=read_annotations)
    def get_file(
        profile_id: str,
        project: str,
        path: str,
        ref: str = "main",
    ) -> JsonObject:
        """Read one UTF-8 repository file."""
        return _client(profile_id).get_file(project, path, ref)

    @mcp.tool(title="GitLab repository tree", annotations=read_annotations)
    def list_tree(
        profile_id: str,
        project: str,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List repository tree entries."""
        return _client(profile_id).list_tree(
            project, path, ref, recursive, page, per_page
        )

    @mcp.tool(title="GitLab code search", annotations=read_annotations)
    def search_code(
        profile_id: str,
        project: str,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """Search repository blobs inside one project."""
        return _client(profile_id).search_code(project, search, ref, page, per_page)

    @mcp.tool(title="GitLab put file", annotations=write_annotations)
    def put_file(
        profile_id: str,
        project: str,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        """Create or update one UTF-8 file on a non-protected branch."""
        return _client(profile_id).put_file(
            project, path, content, branch, commit_message, last_commit_id
        )

    @mcp.tool(title="GitLab delete file", annotations=destructive_annotations)
    def delete_file(
        profile_id: str,
        project: str,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        """Delete one file on a non-protected branch."""
        return _client(profile_id).delete_file(
            project, path, branch, commit_message, last_commit_id
        )

    @mcp.tool(title="GitLab atomic commit", annotations=write_annotations)
    def commit_actions(
        profile_id: str,
        project: str,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> JsonObject:
        """Create one atomic multi-file commit using GitLab repository commit actions."""
        return _client(profile_id).commit_actions(
            project, branch, commit_message, actions, start_branch
        )

    @mcp.tool(title="GitLab list branches", annotations=read_annotations)
    def list_branches(
        profile_id: str,
        project: str,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List repository branches."""
        return _client(profile_id).list_branches(project, search, page, per_page)

    @mcp.tool(title="GitLab create branch", annotations=write_annotations)
    def create_branch(
        profile_id: str,
        project: str,
        branch: str,
        ref: str,
    ) -> JsonObject:
        """Create a non-protected branch from a ref."""
        return _client(profile_id).create_branch(project, branch, ref)

    @mcp.tool(title="GitLab delete branch", annotations=destructive_annotations)
    def delete_branch(
        profile_id: str,
        project: str,
        branch: str,
    ) -> JsonObject:
        """Delete a non-protected repository branch."""
        return _client(profile_id).delete_branch(project, branch)

    @mcp.tool(title="GitLab compare refs", annotations=read_annotations)
    def compare(
        profile_id: str,
        project: str,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> JsonObject:
        """Compare two repository refs."""
        return _client(profile_id).compare(project, from_ref, to_ref, straight)

    @mcp.tool(title="GitLab list merge requests", annotations=read_annotations)
    def list_merge_requests(
        profile_id: str,
        project: str,
        state: str = "opened",
        source_branch: str = "",
        target_branch: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List merge requests for one project."""
        return _client(profile_id).list_merge_requests(
            project,
            state,
            source_branch,
            target_branch,
            page,
            per_page,
        )

    @mcp.tool(title="GitLab get merge request", annotations=read_annotations)
    def get_merge_request(
        profile_id: str,
        project: str,
        iid: int,
    ) -> JsonObject:
        """Read one merge request."""
        return _client(profile_id).get_merge_request(project, iid)

    @mcp.tool(title="GitLab create merge request", annotations=write_annotations)
    def create_merge_request(
        profile_id: str,
        project: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        remove_source_branch: bool = False,
        squash: bool = False,
        draft: bool = False,
    ) -> JsonObject:
        """Create a merge request inside one GitLab project."""
        return _client(profile_id).create_merge_request(
            project,
            source_branch,
            target_branch,
            title,
            description,
            remove_source_branch,
            squash,
            draft,
        )

    @mcp.tool(title="GitLab update merge request", annotations=write_annotations)
    def update_merge_request(
        profile_id: str,
        project: str,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        target_branch: str | None = None,
        remove_source_branch: bool | None = None,
        squash: bool | None = None,
    ) -> JsonObject:
        """Update merge request metadata or state."""
        return _client(profile_id).update_merge_request(
            project,
            iid,
            title,
            description,
            state_event,
            target_branch,
            remove_source_branch,
            squash,
        )

    @mcp.tool(title="GitLab merge merge request", annotations=write_annotations)
    def merge_merge_request(
        profile_id: str,
        project: str,
        iid: int,
        sha: str = "",
        squash: bool | None = None,
        should_remove_source_branch: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> JsonObject:
        """Merge a merge request, optionally pinning the expected source SHA."""
        return _client(profile_id).merge_merge_request(
            project,
            iid,
            sha,
            squash,
            should_remove_source_branch,
            merge_when_pipeline_succeeds,
            merge_commit_message,
            squash_commit_message,
        )

    @mcp.tool(title="GitLab list issues", annotations=read_annotations)
    def list_issues(
        profile_id: str,
        project: str,
        state: str = "opened",
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List project issues."""
        return _client(profile_id).list_issues(project, state, search, page, per_page)

    @mcp.tool(title="GitLab get issue", annotations=read_annotations)
    def get_issue(
        profile_id: str,
        project: str,
        iid: int,
    ) -> JsonObject:
        """Read one project issue."""
        return _client(profile_id).get_issue(project, iid)

    @mcp.tool(title="GitLab create issue", annotations=write_annotations)
    def create_issue(
        profile_id: str,
        project: str,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Create a project issue."""
        return _client(profile_id).create_issue(project, title, description, labels)

    @mcp.tool(title="GitLab update issue", annotations=write_annotations)
    def update_issue(
        profile_id: str,
        project: str,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Update project issue metadata or state."""
        return _client(profile_id).update_issue(
            project, iid, title, description, state_event, labels
        )

    @mcp.tool(title="GitLab issue note", annotations=write_annotations)
    def add_issue_note(
        profile_id: str,
        project: str,
        iid: int,
        body: str,
    ) -> JsonObject:
        """Add a note/comment to an issue."""
        return _client(profile_id).add_issue_note(project, iid, body)

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
        return _client(profile_id).list_pipelines(project, ref, status, page, per_page)

    @mcp.tool(title="GitLab pipeline jobs", annotations=read_annotations)
    def list_pipeline_jobs(
        profile_id: str,
        project: str,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List jobs for one pipeline."""
        return _client(profile_id).list_pipeline_jobs(
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
        return _client(profile_id).job_trace(project, job_id, max_chars)

    @mcp.tool(title="GitLab retry pipeline", annotations=write_annotations)
    def retry_pipeline(
        profile_id: str,
        project: str,
        pipeline_id: int,
    ) -> JsonObject:
        """Retry failed/canceled jobs in a pipeline according to GitLab semantics."""
        return _client(profile_id).retry_pipeline(project, pipeline_id)

    @mcp.tool(title="GitLab cancel pipeline", annotations=destructive_annotations)
    def cancel_pipeline(
        profile_id: str,
        project: str,
        pipeline_id: int,
    ) -> JsonObject:
        """Cancel a running GitLab pipeline."""
        return _client(profile_id).cancel_pipeline(project, pipeline_id)
