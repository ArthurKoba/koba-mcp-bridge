from __future__ import annotations

import json
import uuid
from typing import Any

from fastmcp import Client, FastMCP

from .artifact_store import ArtifactError, ArtifactStore


def _ghidra_url() -> str:
    import os

    value = os.getenv("GHIDRA_MCP_URL", "").strip()
    if not value:
        raise ArtifactError("GHIDRA_MCP_URL is not configured")
    return value


def _decode_result(data: Any) -> Any:
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        data = data["result"]
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    return data


def _decode_call_result(result: Any) -> Any:
    """Decode FastMCP results across structured and legacy content forms."""
    candidates = [
        getattr(result, "data", None),
        getattr(result, "structured_content", None),
    ]
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            candidates.append(text)

    for candidate in candidates:
        if candidate is None:
            continue
        decoded = _decode_result(candidate)
        if decoded is not None:
            return decoded
    return None


async def _current_project(client: Client) -> dict[str, Any]:
    result = await client.call_tool("get_project_info", {})
    info = _decode_call_result(result)
    if not isinstance(info, dict) or not info.get("has_project"):
        raise ArtifactError("no Ghidra project is open")
    project_name = str(info.get("project_name", "")).strip()
    if not project_name:
        raise ArtifactError("Ghidra did not return the current project name")
    return info


async def ghidra_import_artifact_impl(
    artifact_id: str,
    project_folder: str = "/",
    language: str | None = None,
    compiler_spec: str | None = None,
    auto_analyze: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    store = ArtifactStore()
    artifact = store.info(artifact_id)
    server_path = store.path_for(artifact_id)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "artifact_id": artifact["artifact_id"],
            "name": artifact["name"],
            "project_folder": project_folder,
            "language": language,
            "compiler_spec": compiler_spec,
            "auto_analyze": auto_analyze,
        }

    async with Client(_ghidra_url()) as client:
        project = await _current_project(client)
        result = await client.call_tool(
            "import_file",
            {
                "file_path": str(server_path),
                "project_folder": project_folder,
                "language": language,
                "compiler_spec": compiler_spec,
                "auto_analyze": auto_analyze,
            },
        )

    project_name = str(project["project_name"])
    store.add_reference(
        artifact["artifact_id"],
        consumer_type="ghidra-project",
        consumer_id=project_name,
        role="source",
    )
    return {
        "success": True,
        "artifact_id": artifact["artifact_id"],
        "name": artifact["name"],
        "project_name": project_name,
        "ghidra_result": _decode_call_result(result),
    }


async def ghidra_project_sources_impl() -> dict[str, Any]:
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client)
    project_name = str(project["project_name"])
    refs = ArtifactStore().references(
        consumer_type="ghidra-project",
        consumer_id=project_name,
    )
    sources = []
    store = ArtifactStore()
    for ref in refs:
        info = store.info(str(ref["artifact_id"]))
        sources.append(
            {
                "artifact_id": info["artifact_id"],
                "name": info["name"],
                "mime_type": info["mime_type"],
                "size_bytes": info["size_bytes"],
                "role": ref["role"],
            }
        )
    return {
        "project_name": project_name,
        "sources": sources,
        "count": len(sources),
    }


async def _export_to_artifact(
    tool_name: str,
    payload: dict[str, Any],
    suffix: str,
    artifact_name: str,
) -> dict[str, Any]:
    store = ArtifactStore()
    store.ensure()
    temporary_name = f"ghidra-{uuid.uuid4().hex}{suffix}"
    temporary = store.tmp / temporary_name
    payload = dict(payload)
    payload["output_dir"] = str(store.tmp)
    payload["output_name"] = temporary_name

    try:
        async with Client(_ghidra_url()) as client:
            project = await _current_project(client)
            result = await client.call_tool(tool_name, payload)
        if not temporary.is_file():
            raise ArtifactError("Ghidra export completed without producing a file")
        artifact = store.put_file(
            temporary,
            name=artifact_name,
            source="ghidra-export",
            consume=True,
        )
        store.add_reference(
            artifact["artifact_id"],
            consumer_type="ghidra-project",
            consumer_id=str(project["project_name"]),
            role="export",
        )
        return {
            "success": True,
            "artifact": artifact,
            "project_name": str(project["project_name"]),
            "ghidra_result": _decode_call_result(result),
        }
    finally:
        if temporary.exists():
            temporary.unlink()


async def ghidra_export_program_artifact_impl(
    program_name: str,
    artifact_name: str = "",
) -> dict[str, Any]:
    name = artifact_name.strip() or f"{program_name}.gzf"
    return await _export_to_artifact(
        "export_program",
        {"program_name": program_name},
        ".gzf",
        name,
    )


async def ghidra_archive_project_artifact_impl(
    artifact_name: str = "",
) -> dict[str, Any]:
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client)
    project_name = str(project["project_name"])
    name = artifact_name.strip() or f"{project_name}.gar"
    return await _export_to_artifact(
        "archive_project",
        {},
        ".gar",
        name,
    )


def register_reverse_workflow_tools(
    mcp: FastMCP,
    read_annotations: Any,
    write_annotations: Any,
) -> None:
    @mcp.tool(title="Ghidra import artifact", annotations=write_annotations)
    async def ghidra_import_artifact(
        artifact_id: str,
        project_folder: str = "/",
        language: str | None = None,
        compiler_spec: str | None = None,
        auto_analyze: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import an immutable Koba artifact into the currently open Ghidra project."""
        return await ghidra_import_artifact_impl(
            artifact_id,
            project_folder,
            language,
            compiler_spec,
            auto_analyze,
            dry_run,
        )

    @mcp.tool(title="Ghidra project sources", annotations=read_annotations)
    async def ghidra_project_sources() -> dict[str, Any]:
        """List immutable source artifacts retained for the current Ghidra project."""
        return await ghidra_project_sources_impl()

    @mcp.tool(title="Ghidra export program artifact", annotations=write_annotations)
    async def ghidra_export_program_artifact(
        program_name: str,
        artifact_name: str = "",
    ) -> dict[str, Any]:
        """Export a Ghidra program as a GZF and register it as a Koba artifact."""
        return await ghidra_export_program_artifact_impl(program_name, artifact_name)

    @mcp.tool(title="Ghidra archive project artifact", annotations=write_annotations)
    async def ghidra_archive_project_artifact(
        artifact_name: str = "",
    ) -> dict[str, Any]:
        """Archive the current Ghidra project as a GAR and register it as an artifact."""
        return await ghidra_archive_project_artifact_impl(artifact_name)
