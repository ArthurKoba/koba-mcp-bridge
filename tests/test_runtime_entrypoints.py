from __future__ import annotations

import pytest
from fastmcp import Client

from modules.analysis.runtime import mcp as analysis_mcp
from modules.files.runtime import mcp as files_mcp
from modules.github.runtime import mcp as github_mcp
from modules.gitlab.runtime import mcp as gitlab_mcp
from modules.curl.runtime import mcp as http_mcp


async def _tool_names(mcp) -> set[str]:
    async with Client(mcp) as client:
        tools = await client.list_tools()
    return {tool.name for tool in tools}


@pytest.mark.asyncio
async def test_github_runtime_surface_is_isolated() -> None:
    names = await _tool_names(github_mcp)

    assert "github_agent_status" in names
    assert "github_agent_create_pull_request" in names
    assert "github_agent_workflow_runs" in names
    assert "file_status" not in names
    assert "curl_request" not in names
    assert "profiles" not in names


@pytest.mark.asyncio
async def test_gitlab_runtime_surface_is_isolated() -> None:
    names = await _tool_names(gitlab_mcp)

    assert "profiles" in names
    assert "profile_status" in names
    assert "create_merge_request" in names
    assert "github_agent_status" not in names
    assert "file_status" not in names
    assert "curl_request" not in names


@pytest.mark.asyncio
async def test_files_runtime_surface_is_isolated() -> None:
    names = await _tool_names(files_mcp)

    assert "file_status" in names
    assert "file_ingest" in names
    assert "file_extract" in names
    assert "curl_request" not in names
    assert "github_agent_status" not in names
    assert "profiles" not in names


@pytest.mark.asyncio
async def test_http_runtime_surface_is_isolated() -> None:
    names = await _tool_names(http_mcp)

    assert "curl_presets" in names
    assert "curl_request" in names
    assert "curl_download" in names
    assert "curl_stream_capture" in names
    assert "file_status" not in names
    assert "github_agent_status" not in names
    assert "profiles" not in names


@pytest.mark.asyncio
async def test_analysis_runtime_surface_is_isolated() -> None:
    names = await _tool_names(analysis_mcp)

    assert "ghidra_import_file" in names
    assert "ghidra_project_sources" in names
    assert "ghidra_export_program_file" in names
    assert "file_status" not in names
    assert "curl_request" not in names
    assert "github_agent_status" not in names
    assert "profiles" not in names
