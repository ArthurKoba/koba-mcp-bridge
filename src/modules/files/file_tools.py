from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .file_ingress import ClientFile, FileUploadManager, ingest_file
from .file_store import FileStore


def register_file_tools(
    mcp: FastMCP,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="File status", annotations=read_annotations)
    def file_status() -> JsonObject:
        """Inspect the universal persistent MCP Bridge file store and active uploads."""
        result = FileStore().status()
        result["active_uploads"] = FileUploadManager().active_count()
        return result

    @mcp.tool(
        title="File ingest",
        annotations=write_annotations,
        meta={"openai/fileParams": ["file"]},
    )
    def file_ingest(
        file: ClientFile,
        name: str = "",
        mime_type: str = "",
        expected_size: int | None = None,
        expected_sha256: str = "",
    ) -> JsonObject:
        """Ingest a client attachment/file directly into immutable file storage.

        Pass the client-visible attachment/file as `file`. ChatGPT resolves this
        marked file parameter into a structured payload containing an authorized
        temporary download URL plus file metadata. MCP Bridge streams the bytes server-side;
        do not base64-encode chat attachments for this tool.

        Use file_upload_* only as the generic resumable fallback for clients that
        cannot provide a file-capable argument.
        """
        return ingest_file(
            file=file,
            name=name,
            mime_type=mime_type,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

    @mcp.tool(title="File upload begin", annotations=write_annotations)
    def file_upload_begin(
        name: str,
        size_bytes: int,
        mime_type: str = "",
        expected_sha256: str = "",
    ) -> JsonObject:
        """Create a resumable upload session for an agent-controlled file transfer."""
        return FileUploadManager().begin(
            name=name,
            size_bytes=size_bytes,
            mime_type=mime_type,
            expected_sha256=expected_sha256,
        )

    @mcp.tool(title="File upload status", annotations=read_annotations)
    def file_upload_status(upload_id: str) -> JsonObject:
        """Return upload progress and the exact next byte offset."""
        return FileUploadManager().status(upload_id)

    @mcp.tool(title="File upload list", annotations=read_annotations)
    def file_upload_list(
        state: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> JsonObject:
        """List resumable upload sessions so agents can recover interrupted transfers."""
        return FileUploadManager().list(state=state, offset=offset, limit=limit)

    @mcp.tool(title="File upload write", annotations=write_annotations)
    def file_upload_write(
        upload_id: str,
        offset: int,
        data_base64: str,
    ) -> JsonObject:
        """Append one base64-encoded chunk at the exact next offset.

        The server rejects oversized, reordered, sparse, or overlapping chunks.
        Use the returned next_offset for the following call.
        """
        return FileUploadManager().write(upload_id, offset, data_base64)

    @mcp.tool(title="File upload finish", annotations=write_annotations)
    def file_upload_finish(upload_id: str) -> JsonObject:
        """Verify size/SHA-256, commit the upload, and return its immutable file_id."""
        return FileUploadManager().finish(upload_id)

    @mcp.tool(title="File upload cancel", annotations=destructive_annotations)
    def file_upload_cancel(upload_id: str) -> JsonObject:
        """Cancel an unfinished upload and discard its staged bytes."""
        return FileUploadManager().cancel(upload_id)

    @mcp.tool(title="File upload cleanup", annotations=destructive_annotations)
    def file_upload_cleanup(
        older_than_hours: int = 24,
        dry_run: bool = True,
        limit: int = 1000,
    ) -> JsonObject:
        """Preview or remove stale upload-session state without deleting committed files."""
        return FileUploadManager().cleanup(
            older_than_hours=older_than_hours,
            dry_run=dry_run,
            limit=limit,
        )

    @mcp.tool(title="File list", annotations=read_annotations)
    def file_list(
        query: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> JsonObject:
        """List immutable files by metadata. Physical filesystem paths are private."""
        return FileStore().list(query=query, offset=offset, limit=limit)

    @mcp.tool(title="File info", annotations=read_annotations)
    def file_info(file_id: str) -> JsonObject:
        """Return metadata, aliases, collections, and consumer references."""
        return FileStore().info(file_id)

    @mcp.tool(title="File read", annotations=read_annotations)
    def file_read(
        file_id: str,
        offset: int = 0,
        length: int = 1024 * 1024,
    ) -> JsonObject:
        """Read file bytes as base64 by immutable file_id."""
        return FileStore().read(file_id, offset=offset, length=length)

    @mcp.tool(title="File create text", annotations=write_annotations)
    def file_create_text(
        name: str,
        content: str,
        mime_type: str = "text/plain; charset=utf-8",
    ) -> JsonObject:
        """Create an immutable text file generated by an agent or backend."""
        return FileStore().put_text(name=name, content=content, mime_type=mime_type)

    @mcp.tool(title="File extract", annotations=write_annotations)
    def file_extract(file_id: str) -> JsonObject:
        """Extract a tar/zip file into a content-addressed collection."""
        return FileStore().extract(file_id)

    @mcp.tool(title="File collection list", annotations=read_annotations)
    def file_collection_list(
        collection_id: str,
        prefix: str = "",
        offset: int = 0,
        limit: int = 200,
    ) -> JsonObject:
        """List files in an extracted collection without exposing server paths."""
        return FileStore().collection_list(
            collection_id,
            prefix=prefix,
            offset=offset,
            limit=limit,
        )

    @mcp.tool(title="File collection delete", annotations=destructive_annotations)
    def file_collection_delete(collection_id: str) -> JsonObject:
        """Delete a collection manifest while leaving its immutable member files intact."""
        return FileStore().collection_delete(collection_id)

    @mcp.tool(title="File collection resolve", annotations=read_annotations)
    def file_collection_resolve(
        collection_id: str,
        path: str,
    ) -> JsonObject:
        """Resolve one collection-relative path to its immutable file_id."""
        return FileStore().collection_resolve(collection_id, path)

    @mcp.tool(title="File references", annotations=read_annotations)
    def file_references(
        consumer_type: str = "",
        consumer_id: str = "",
    ) -> JsonObject:
        """List durable links from files to consumers such as Ghidra projects."""
        refs = FileStore().references(
            consumer_type=consumer_type,
            consumer_id=consumer_id,
        )
        return {"references": refs, "count": len(refs)}

    @mcp.tool(title="File release reference", annotations=destructive_annotations)
    def file_release_reference(
        file_id: str,
        consumer_type: str,
        consumer_id: str,
        role: str = "source",
    ) -> JsonObject:
        """Release one consumer reference so an unused file can later be collected."""
        return FileStore().release_reference(
            file_id,
            consumer_type,
            consumer_id,
            role,
        )

    @mcp.tool(title="File delete", annotations=destructive_annotations)
    def file_delete(
        file_id: str,
        force: bool = False,
    ) -> JsonObject:
        """Delete an unreferenced file. force=true also removes its links."""
        return FileStore().delete(file_id, force=force)

    @mcp.tool(title="File garbage collect", annotations=destructive_annotations)
    def file_gc(
        dry_run: bool = True,
        limit: int = 1000,
    ) -> JsonObject:
        """Find or delete files that are not referenced by any consumer or collection."""
        return FileStore().gc(dry_run=dry_run, limit=limit)
