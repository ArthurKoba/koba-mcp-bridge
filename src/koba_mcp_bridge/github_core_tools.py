from __future__ import annotations

from typing import Any, Callable

from fastmcp import FastMCP

from .github_identity import GitHubPrettyIdentityClient


def register_github_core_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubPrettyIdentityClient],
    read_annotations: Any,
    write_annotations: Any,
    destructive_annotations: Any,
) -> None:
    @mcp.tool(title="GitHub agent list repositories", annotations=read_annotations)
    def github_agent_list_repositories() -> dict[str, object]:
        return client_factory().list_repositories()

    @mcp.tool(title="GitHub agent status", annotations=read_annotations)
    def github_agent_status(repository: str) -> dict[str, object]:
        return client_factory().status(repository)

    @mcp.tool(title="GitHub agent get file", annotations=read_annotations)
    def github_agent_get_file(
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, object]:
        return client_factory().get_file(repository, path, ref)

    @mcp.tool(title="GitHub agent list branches", annotations=read_annotations)
    def github_agent_list_branches(repository: str) -> dict[str, object]:
        return client_factory().list_branches(repository)

    @mcp.tool(title="GitHub agent create branch", annotations=write_annotations)
    def github_agent_create_branch(
        repository: str,
        branch: str,
        from_branch: str = "main",
    ) -> dict[str, object]:
        return client_factory().create_branch(repository, branch, from_branch)

    @mcp.tool(title="GitHub agent put file", annotations=write_annotations)
    def github_agent_put_file(
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        return client_factory().put_file(repository, path, content, message, branch)

    @mcp.tool(title="GitHub agent delete file", annotations=destructive_annotations)
    def github_agent_delete_file(
        repository: str,
        path: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        return client_factory().delete_file(repository, path, message, branch)

    @mcp.tool(title="GitHub agent compare refs", annotations=read_annotations)
    def github_agent_compare(
        repository: str,
        base: str,
        head: str,
    ) -> dict[str, object]:
        return client_factory().compare(repository, base, head)

    @mcp.tool(title="GitHub agent fast-forward branch", annotations=write_annotations)
    def github_agent_fast_forward(
        repository: str,
        branch: str,
        to_ref: str,
    ) -> dict[str, object]:
        return client_factory().fast_forward(repository, branch, to_ref)
