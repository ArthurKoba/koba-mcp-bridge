from __future__ import annotations

import base64
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
    """Recursively unwrap Ghidra/FastMCP result envelopes and JSON strings."""
    value = data
    for _ in range(8):
        if isinstance(value, dict) and "result" in value:
            nested = value["result"]
            if nested is value:
                return value
            value = nested
            continue
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return value
            if decoded == value:
                return value
            value = decoded
            continue
        return value
    return value


def _decode_call_result(result: Any) -> Any:
    """Decode FastMCP results across structured and legacy content forms."""
    candidates = [
        getattr(result, "structured_content", None),
        getattr(result, "data", None),
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


def _require_backend_success(result: Any, operation: str) -> dict[str, Any]:
    decoded = _decode_call_result(result)
    if not isinstance(decoded, dict):
        raise ArtifactError(f"Ghidra {operation} returned an invalid response")
    error = str(decoded.get("error", "")).strip()
    if error:
        raise ArtifactError(f"Ghidra {operation} failed: {error}")
    if decoded.get("success") is False:
        raise ArtifactError(f"Ghidra {operation} failed")
    return decoded


async def _cancel_stage(client: Client, stage_id: str) -> None:
    if not stage_id:
        return
    try:
        await client.call_tool("artifact_stage_cancel", {"stage_id": stage_id})
    except Exception:
        pass


async def _stage_artifact_for_ghidra(
    client: Client,
    store: ArtifactStore,
    artifact: dict[str, Any],
) -> tuple[str, str]:
    begin_result = await client.call_tool(
        "artifact_stage_begin",
        {
            "name": str(artifact["name"]),
            "size_bytes": int(artifact["size_bytes"]),
            "sha256": str(artifact["sha256"]),
        },
    )
    begin = _require_backend_success(begin_result, "artifact staging begin")
    stage_id = str(begin.get("stage_id", "")).strip()
    if not stage_id:
        raise ArtifactError("Ghidra artifact staging did not return stage_id")

    chunk_bytes = int(begin.get("chunk_bytes", 1024 * 1024))
    if chunk_bytes <= 0 or chunk_bytes > 8 * 1024 * 1024:
        await _cancel_stage(client, stage_id)
        raise ArtifactError("Ghidra artifact staging returned an invalid chunk size")

    path = store.path_for(str(artifact["artifact_id"]))
    offset = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_bytes)
                if not chunk:
                    break
                write_result = await client.call_tool(
                    "artifact_stage_write",
                    {
                        "stage_id": stage_id,
                        "offset": offset,
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
                write = _require_backend_success(write_result, "artifact staging write")
                next_offset = int(write.get("next_offset", -1))
                expected_next = offset + len(chunk)
                if next_offset != expected_next:
                    raise ArtifactError(
                        "Ghidra artifact staging returned an unexpected next_offset"
                    )
                offset = next_offset

        finish_result = await client.call_tool(
            "artifact_stage_finish",
            {"stage_id": stage_id},
        )
        finish = _require_backend_success(finish_result, "artifact staging finish")
        staged_path = str(finish.get("path", "")).strip()
        if not staged_path:
            raise ArtifactError("Ghidra artifact staging did not return a staged path")
        if str(finish.get("sha256", "")).casefold() != str(artifact["sha256"]).casefold():
            raise ArtifactError("Ghidra artifact staging SHA-256 verification failed")
        return stage_id, staged_path
    except Exception:
        await _cancel_stage(client, stage_id)
        raise


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

    stage_id = ""
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client)
        try:
            stage_id, staged_path = await _stage_artifact_for_ghidra(
                client,
                store,
                artifact,
            )
            result = await client.call_tool(
                "import_file",
                {
                    "file_path": staged_path,
                    "project_folder": project_folder,
                    "language": language,
                    "compiler_spec": compiler_spec,
                    "auto_analyze": auto_analyze,
                },
            )
            ghidra_result = _require_backend_success(result, "artifact import")
        finally:
            await _cancel_stage(client, stage_id)

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
        "ghidra_result": ghidra_result,
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
