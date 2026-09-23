from __future__ import annotations

import base64
import json
import uuid
from contextlib import suppress
from typing import Any

from fastmcp import Client, FastMCP

from .file_store import FileError, FileStore


def _ghidra_url() -> str:
    import os

    value = os.getenv("GHIDRA_MCP_URL", "").strip()
    if not value:
        raise FileError("GHIDRA_MCP_URL is not configured")
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
        raise FileError(f"Ghidra {operation} returned an invalid response")
    error = str(decoded.get("error", "")).strip()
    if error:
        raise FileError(f"Ghidra {operation} failed: {error}")
    if decoded.get("success") is False:
        raise FileError(f"Ghidra {operation} failed")
    return decoded


async def _cancel_stage(client: Client, project_id: str, stage_id: str) -> None:
    if not stage_id:
        return
    with suppress(Exception):
        await client.call_tool(
            "file_stage_cancel",
            {"project_id": project_id, "stage_id": stage_id},
        )


async def _stage_file_for_ghidra(
    client: Client,
    store: FileStore,
    file: dict[str, Any],
    project_id: str,
) -> tuple[str, str]:
    begin_result = await client.call_tool(
        "file_stage_begin",
        {
            "project_id": project_id,
            "name": str(file["name"]),
            "size_bytes": int(file["size_bytes"]),
            "sha256": str(file["sha256"]),
        },
    )
    begin = _require_backend_success(begin_result, "file staging begin")
    stage_id = str(begin.get("stage_id", "")).strip()
    if not stage_id:
        raise FileError("Ghidra file staging did not return stage_id")

    chunk_bytes = int(begin.get("chunk_bytes", 1024 * 1024))
    if chunk_bytes <= 0 or chunk_bytes > 8 * 1024 * 1024:
        await _cancel_stage(client, project_id, stage_id)
        raise FileError("Ghidra file staging returned an invalid chunk size")

    path = store.path_for(str(file["file_id"]))
    offset = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_bytes)
                if not chunk:
                    break
                write_result = await client.call_tool(
                    "file_stage_write",
                    {
                        "project_id": project_id,
                        "stage_id": stage_id,
                        "offset": offset,
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
                write = _require_backend_success(write_result, "file staging write")
                next_offset = int(write.get("next_offset", -1))
                expected_next = offset + len(chunk)
                if next_offset != expected_next:
                    raise FileError(
                        "Ghidra file staging returned an unexpected next_offset"
                    )
                offset = next_offset

        finish_result = await client.call_tool(
            "file_stage_finish",
            {"project_id": project_id, "stage_id": stage_id},
        )
        finish = _require_backend_success(finish_result, "file staging finish")
        staged_path = str(finish.get("path", "")).strip()
        if not staged_path:
            raise FileError("Ghidra file staging did not return a staged path")
        if str(finish.get("sha256", "")).casefold() != str(file["sha256"]).casefold():
            raise FileError("Ghidra file staging SHA-256 verification failed")
        return stage_id, staged_path
    except Exception:
        await _cancel_stage(client, project_id, stage_id)
        raise


async def _current_project(client: Client, project_id: str) -> dict[str, Any]:
    result = await client.call_tool(
        "get_project_info",
        {"project_id": project_id},
    )
    info = _decode_call_result(result)
    if not isinstance(info, dict) or not info.get("has_project"):
        raise FileError("no Ghidra project is open")
    project_name = str(info.get("project_name", "")).strip()
    if not project_name:
        raise FileError("Ghidra did not return the current project name")
    return info


async def ghidra_import_file_impl(
    project_id: str,
    file_id: str,
    project_folder: str = "/",
    language: str | None = None,
    compiler_spec: str | None = None,
    auto_analyze: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    store = FileStore()
    file = store.info(file_id)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "project_id": project_id,
            "file_id": file["file_id"],
            "name": file["name"],
            "project_folder": project_folder,
            "language": language,
            "compiler_spec": compiler_spec,
            "auto_analyze": auto_analyze,
        }

    stage_id = ""
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client, project_id)
        try:
            stage_id, staged_path = await _stage_file_for_ghidra(
                client,
                store,
                file,
                project_id,
            )
            result = await client.call_tool(
                "import_file",
                {
                    "project_id": project_id,
                    "file_path": staged_path,
                    "project_folder": project_folder,
                    "language": language,
                    "compiler_spec": compiler_spec,
                    "auto_analyze": auto_analyze,
                },
            )
            ghidra_result = _require_backend_success(result, "file import")
        finally:
            await _cancel_stage(client, project_id, stage_id)

    project_name = str(project["project_name"])
    store.add_reference(
        file["file_id"],
        consumer_type="ghidra-project",
        consumer_id=project_id,
        role="source",
    )
    return {
        "success": True,
        "project_id": project_id,
        "file_id": file["file_id"],
        "name": file["name"],
        "project_name": project_name,
        "ghidra_result": ghidra_result,
    }


async def ghidra_project_sources_impl(project_id: str) -> dict[str, Any]:
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client, project_id)
    project_name = str(project["project_name"])
    refs = FileStore().references(
        consumer_type="ghidra-project",
        consumer_id=project_id,
    )
    sources = []
    store = FileStore()
    for ref in refs:
        info = store.info(str(ref["file_id"]))
        sources.append(
            {
                "file_id": info["file_id"],
                "name": info["name"],
                "mime_type": info["mime_type"],
                "size_bytes": info["size_bytes"],
                "role": ref["role"],
            }
        )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "sources": sources,
        "count": len(sources),
    }


async def _export_to_file(
    project_id: str,
    tool_name: str,
    payload: dict[str, Any],
    suffix: str,
    file_name: str,
) -> dict[str, Any]:
    store = FileStore()
    store.ensure()
    temporary_name = f"ghidra-{uuid.uuid4().hex}{suffix}"
    temporary = store.tmp / temporary_name
    payload = dict(payload)
    payload["project_id"] = project_id
    payload["output_dir"] = str(store.tmp)
    payload["output_name"] = temporary_name

    try:
        async with Client(_ghidra_url()) as client:
            project = await _current_project(client, project_id)
            result = await client.call_tool(tool_name, payload)
        if not temporary.is_file():
            raise FileError("Ghidra export completed without producing a file")
        file = store.put_file(
            temporary,
            name=file_name,
            source="ghidra-export",
            consume=True,
        )
        store.add_reference(
            file["file_id"],
            consumer_type="ghidra-project",
            consumer_id=project_id,
            role="export",
        )
        return {
            "success": True,
            "project_id": project_id,
            "file": file,
            "project_name": str(project["project_name"]),
            "ghidra_result": _decode_call_result(result),
        }
    finally:
        if temporary.exists():
            temporary.unlink()


async def ghidra_export_program_file_impl(
    project_id: str,
    program_name: str,
    file_name: str = "",
) -> dict[str, Any]:
    name = file_name.strip() or f"{program_name}.gzf"
    return await _export_to_file(
        project_id,
        "export_program",
        {"program_name": program_name},
        ".gzf",
        name,
    )


async def ghidra_archive_project_file_impl(
    project_id: str,
    file_name: str = "",
) -> dict[str, Any]:
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client, project_id)
    project_name = str(project["project_name"])
    name = file_name.strip() or f"{project_name}.gar"
    return await _export_to_file(
        project_id,
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
    @mcp.tool(title="Ghidra import file", annotations=write_annotations)
    async def ghidra_import_file(
        project_id: str,
        file_id: str,
        project_folder: str = "/",
        language: str | None = None,
        compiler_spec: str | None = None,
        auto_analyze: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import an immutable Koba file into the explicitly selected Ghidra project."""
        return await ghidra_import_file_impl(
            project_id,
            file_id,
            project_folder,
            language,
            compiler_spec,
            auto_analyze,
            dry_run,
        )

    @mcp.tool(title="Ghidra project sources", annotations=read_annotations)
    async def ghidra_project_sources(project_id: str) -> dict[str, Any]:
        """List immutable source files retained for one explicit Ghidra project."""
        return await ghidra_project_sources_impl(project_id)

    @mcp.tool(title="Ghidra export program file", annotations=write_annotations)
    async def ghidra_export_program_file(
        project_id: str,
        program_name: str,
        file_name: str = "",
    ) -> dict[str, Any]:
        """Export a Ghidra program as a GZF and register it as a Koba file."""
        return await ghidra_export_program_file_impl(
            project_id,
            program_name,
            file_name,
        )

    @mcp.tool(title="Ghidra archive project file", annotations=write_annotations)
    async def ghidra_archive_project_file(
        project_id: str,
        file_name: str = "",
    ) -> dict[str, Any]:
        """Archive one explicit Ghidra project as a GAR and register it as an file."""
        return await ghidra_archive_project_file_impl(project_id, file_name)
