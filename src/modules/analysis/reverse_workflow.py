from __future__ import annotations

import base64
import os
import uuid
from contextlib import suppress
from typing import TypeVar, cast

from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from common.models import JsonObject, JsonValue, json_loads, json_object, json_value

from modules.files.file_store import FileError, FileStore
from modules.files.models import FileInfo, FileReference

from .models import (
    BackendStatus,
    ExportFileResponse,
    ImportDryRunResponse,
    ImportFileResponse,
    ProjectInfo,
    ProjectSource,
    ProjectSourcesResponse,
    StageBeginResponse,
    StageFinishResponse,
    StageWriteResponse,
)

BackendModel = TypeVar("BackendModel", bound=BackendStatus)


def _ghidra_url() -> str:
    value = os.getenv("GHIDRA_MCP_URL", "").strip()
    if not value:
        raise FileError("GHIDRA_MCP_URL is not configured")
    return value


def _decode_result(data: object) -> JsonValue:
    """Recursively unwrap Ghidra/FastMCP result envelopes and JSON strings."""
    value: object = data
    for _ in range(8):
        if isinstance(value, dict) and "result" in value:
            nested = value["result"]
            if nested is value:
                return json_value(value, context="Ghidra result")
            value = nested
            continue
        if isinstance(value, str):
            try:
                decoded = json_loads(value, context="Ghidra result")
            except ValueError:
                return value
            if decoded == value:
                return value
            value = decoded
            continue
        return json_value(value, context="Ghidra result")
    return json_value(value, context="Ghidra result")


def _decode_call_result(result: object) -> JsonValue | None:
    """Decode FastMCP results across structured and legacy content forms."""
    candidates: list[object | None] = [
        cast(object | None, getattr(result, "structured_content", None)),
        cast(object | None, getattr(result, "data", None)),
    ]
    content = cast(object | None, getattr(result, "content", None))
    if isinstance(content, list):
        for block in content:
            text = cast(object | None, getattr(block, "text", None))
            if isinstance(text, str):
                candidates.append(text)

    for candidate in candidates:
        if candidate is None:
            continue
        decoded = _decode_result(candidate)
        if decoded is not None:
            return decoded
    return None


def _require_backend_success(result: object, operation: str) -> JsonObject:
    decoded = _decode_call_result(result)
    if decoded is None:
        raise FileError(f"Ghidra {operation} returned no response")
    try:
        payload = json_object(decoded, context=f"Ghidra {operation} response")
        status = BackendStatus.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        raise FileError(f"Ghidra {operation} returned an invalid response") from exc

    if status.error:
        raise FileError(f"Ghidra {operation} failed: {status.error}")
    if status.success is False:
        raise FileError(f"Ghidra {operation} failed")
    return payload


def _backend_model(
    result: object,
    operation: str,
    model: type[BackendModel],
) -> BackendModel:
    payload = _require_backend_success(result, operation)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise FileError(f"Ghidra {operation} response is incomplete") from exc


async def _cancel_stage(client: Client, project_id: str, stage_id: str) -> None:
    if not stage_id:
        return
    with suppress(Exception):
        await client.call_tool(
            "artifact_stage_cancel",
            {"project_id": project_id, "stage_id": stage_id},
        )


async def _stage_file_for_ghidra(
    client: Client,
    store: FileStore,
    file: FileInfo,
    project_id: str,
) -> tuple[str, str]:
    begin_result = await client.call_tool(
        "artifact_stage_begin",
        {
            "project_id": project_id,
            "name": file.name,
            "size_bytes": file.size_bytes,
            "sha256": file.sha256,
        },
    )
    begin = _backend_model(
        begin_result,
        "file staging begin",
        StageBeginResponse,
    )
    stage_id = begin.stage_id
    chunk_bytes = begin.chunk_bytes

    path = store.path_for(file.file_id)
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
                        "project_id": project_id,
                        "stage_id": stage_id,
                        "offset": offset,
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
                write = _backend_model(
                    write_result,
                    "file staging write",
                    StageWriteResponse,
                )
                next_offset = write.next_offset
                expected_next = offset + len(chunk)
                if next_offset != expected_next:
                    raise FileError(
                        "Ghidra file staging returned an unexpected next_offset"
                    )
                offset = next_offset

        finish_result = await client.call_tool(
            "artifact_stage_finish",
            {"project_id": project_id, "stage_id": stage_id},
        )
        finish = _backend_model(
            finish_result,
            "file staging finish",
            StageFinishResponse,
        )
        if finish.sha256.casefold() != file.sha256.casefold():
            raise FileError("Ghidra file staging SHA-256 verification failed")
        return stage_id, finish.path
    except Exception:
        await _cancel_stage(client, project_id, stage_id)
        raise


async def _current_project(client: Client, project_id: str) -> ProjectInfo:
    result = await client.call_tool(
        "get_project_info",
        {"project_id": project_id},
    )
    info = _backend_model(result, "project info", ProjectInfo)
    if not info.has_project:
        raise FileError("no Ghidra project is open")
    return info


async def ghidra_import_file_impl(
    project_id: str,
    file_id: str,
    project_folder: str = "/",
    language: str | None = None,
    compiler_spec: str | None = None,
    auto_analyze: bool = True,
    dry_run: bool = False,
) -> JsonObject:
    store = FileStore()
    file = FileInfo.model_validate(store.info(file_id))

    if dry_run:
        return ImportDryRunResponse(
            success=True,
            dry_run=True,
            project_id=project_id,
            file_id=file.file_id,
            name=file.name,
            project_folder=project_folder,
            language=language,
            compiler_spec=compiler_spec,
            auto_analyze=auto_analyze,
        ).to_json()

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

    project_name = project.project_name
    store.add_reference(
        file.file_id,
        consumer_type="ghidra-project",
        consumer_id=project_id,
        role="source",
    )
    return ImportFileResponse(
        success=True,
        project_id=project_id,
        file_id=file.file_id,
        name=file.name,
        project_name=project_name,
        ghidra_result=ghidra_result,
    ).to_json()


async def ghidra_project_sources_impl(project_id: str) -> JsonObject:
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client, project_id)
    project_name = project.project_name
    refs = FileStore().references(
        consumer_type="ghidra-project",
        consumer_id=project_id,
    )
    sources: list[ProjectSource] = []
    store = FileStore()
    for raw_ref in refs:
        ref = FileReference.model_validate(raw_ref)
        if ref.file_id is None:
            continue
        info = FileInfo.model_validate(store.info(ref.file_id))
        sources.append(
            ProjectSource(
                file_id=info.file_id,
                name=info.name,
                mime_type=info.mime_type,
                size_bytes=info.size_bytes,
                role=ref.role,
            )
        )
    return ProjectSourcesResponse(
        project_id=project_id,
        project_name=project_name,
        sources=sources,
        count=len(sources),
    ).to_json()


async def _export_to_file(
    project_id: str,
    tool_name: str,
    payload: JsonObject,
    suffix: str,
    file_name: str,
) -> JsonObject:
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
        file = FileInfo.model_validate(
            store.put_file(
            temporary,
            name=file_name,
            source="ghidra-export",
            consume=True,
        )
        )
        store.add_reference(
            file.file_id,
            consumer_type="ghidra-project",
            consumer_id=project_id,
            role="export",
        )
        return ExportFileResponse(
            success=True,
            project_id=project_id,
            file=file,
            project_name=project.project_name,
            ghidra_result=_decode_call_result(result),
        ).to_json()
    finally:
        if temporary.exists():
            temporary.unlink()


async def ghidra_export_program_file_impl(
    project_id: str,
    program_name: str,
    file_name: str = "",
) -> JsonObject:
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
) -> JsonObject:
    async with Client(_ghidra_url()) as client:
        project = await _current_project(client, project_id)
    project_name = project.project_name
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
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
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
    ) -> JsonObject:
        """Import an immutable MCP Bridge file into the explicitly selected Ghidra project."""
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
    async def ghidra_project_sources(project_id: str) -> JsonObject:
        """List immutable source files retained for one explicit Ghidra project."""
        return await ghidra_project_sources_impl(project_id)

    @mcp.tool(title="Ghidra export program file", annotations=write_annotations)
    async def ghidra_export_program_file(
        project_id: str,
        program_name: str,
        file_name: str = "",
    ) -> JsonObject:
        """Export a Ghidra program as a GZF and register it as an MCP Bridge file."""
        return await ghidra_export_program_file_impl(
            project_id,
            program_name,
            file_name,
        )

    @mcp.tool(title="Ghidra archive project file", annotations=write_annotations)
    async def ghidra_archive_project_file(
        project_id: str,
        file_name: str = "",
    ) -> JsonObject:
        """Archive one explicit Ghidra project as a GAR and register it as an file."""
        return await ghidra_archive_project_file_impl(project_id, file_name)
