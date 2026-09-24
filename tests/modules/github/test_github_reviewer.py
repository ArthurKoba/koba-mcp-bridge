from __future__ import annotations

import pytest

from common.account_contracts import ResolvedAccount
from common.settings import GitHubPolicySettings
from modules.github.github_identity import GitHubPrettyIdentityClient


def _account() -> ResolvedAccount:
    return ResolvedAccount(
        id="11111111-1111-1111-1111-111111111111",
        alias="github-reviewer",
        provider="github",
        auth_type="github_app",
        base_url="https://api.github.com",
        external_id="888",
        verify_tls=True,
        ca_cert_pem=None,
        enabled=True,
        created_at="2026-09-23T00:00:00+00:00",
        updated_at="2026-09-23T00:00:00+00:00",
        credential="private-key-material",
    )


def test_github_client_is_built_from_explicit_account() -> None:
    policy = GitHubPolicySettings(
        protected_branches=frozenset({"main", "master"}),
        required_checks=("test", "docker"),
        required_reviewers=("reviewer[bot]",),
    )

    client = GitHubPrettyIdentityClient.from_account(_account(), policy)

    assert client.app_id == "888"
    assert client.private_key == "private-key-material"
    assert client.account_id == _account().id
    assert client.required_reviewers == ("reviewer[bot]",)


@pytest.mark.asyncio
async def test_reviewer_tool_surface_requires_account_id_and_excludes_mutations() -> None:
    from fastmcp import Client, FastMCP
    from mcp.types import ToolAnnotations

    from modules.github.github_reviewer_tools import register_github_reviewer_tools

    reviewer_mcp = FastMCP("reviewer-surface-test")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    review_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )

    def factory(account_id: str):
        assert account_id
        return GitHubPrettyIdentityClient.from_account(
            _account(),
            GitHubPolicySettings(),
        )

    register_github_reviewer_tools(
        reviewer_mcp,
        factory,
        read_only,
        review_write,
    )

    async with Client(reviewer_mcp) as client:
        tools = await client.list_tools()

    by_name = {tool.name: tool for tool in tools}
    assert "github_reviewer_list_repositories" in by_name
    assert "github_reviewer_create_review" in by_name
    assert "github_reviewer_get_file" in by_name
    assert "account_id" in by_name["github_reviewer_get_file"].input_schema["properties"]
    assert not any("put_file" in name for name in by_name)
    assert not any("delete_file" in name for name in by_name)
    assert not any("merge_pull" in name for name in by_name)
