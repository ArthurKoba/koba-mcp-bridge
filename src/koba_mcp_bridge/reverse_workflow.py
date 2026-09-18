from __future__ import annotations

import os
from typing import Any

from fastmcp import Client, FastMCP

from .artifact_storage import ArtifactError, _rel, _resolve


def _ghidra_url() -> str:
    value = os.getenv("GHIDRA_MCP_URL", "").strip()
    if not value:
        raise ArtifactError("GHIDRA_MCP_URL is not configured")
    return value


async def ghidra_import_artifact_impl(
    artifact_path: str,
    project_folder: str = "/",
    language: str | None = None,
    compiler_spec: str | None = None,
    auto_analyze: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    target = _resolve(artifact_path)
    if not target.is_file():
        raise ArtifactError("artifact_path is not a file")

    payload: dict[str, Any] = {
        "file_path": str(target),
        "project_folder": project_folder,
        "language": language,
        "compiler_spec": compiler_spec,
        "auto_analyze": auto_analyze,
    }

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "artifact_path": _rel(target),
            "server_path": str(target),
            "project_folder": project_folder,
            "language": language,
            "compiler_spec": compiler_spec,
            "auto_analyze": auto_analyze,
        }

    async with Client(_ghidra_url()) as client:
        result = await client.call_tool("import_file", payload)

    return {
        "success": True,
        "artifact_path": _rel(target),
        "server_path": str(target),
        "ghidra_result": result.data,
    }


def register_reverse_workflow_tools(
    mcp: FastMCP,
    write_annotations: Any,
) -> None:
    @mcp.tool(title="Ghidra import artifact", annotations=write_annotations)
    async def ghidra_import_artifact(
        artifact_path: str,
        project_folder: str = "/",
        language: str | None = None,
        compiler_spec: str | None = None,
        auto_analyze: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import a Koba artifact into the currently open Ghidra project.

        artifact_path is relative to ARTIFACT_ROOT, for example
        inbox/firmware/Sofia or workspaces/svi252b/lib/libfoo.so.
        Never pass a client-local /mnt path or manually copy files into /projects.
        """
        return await ghidra_import_artifact_impl(
            artifact_path,
            project_folder,
            language,
            compiler_spec,
            auto_analyze,
            dry_run,
        )
