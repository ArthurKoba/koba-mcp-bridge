from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .artifact_ingress import ArtifactUploadManager, ClientFile, ingest_file
from .artifact_store import ArtifactStore


def register_artifact_tools(
    mcp: FastMCP,
    read_annotations: Any,
    write_annotations: Any,
    destructive_annotations: Any,
) -> None:
    @mcp.tool(title="Artifact status", annotations=read_annotations)
    def artifact_status() -> dict[str, Any]:
        """Inspect the universal persistent Koba artifact store and active uploads."""
        result = ArtifactStore().status()
        result["active_uploads"] = ArtifactUploadManager().active_count()
        return result

    @mcp.tool(
        title="Artifact ingest attachment",
        annotations=write_annotations,
        meta={"openai/fileParams": ["file"]},
    )
    def artifact_ingest_attachment(
        file: ClientFile,
        name: str = "",
        mime_type: str = "",
        expected_size: int | None = None,
        expected_sha256: str = "",
    ) -> dict[str, Any]:
        """Ingest a client attachment/file directly into immutable artifact storage.

        Pass the client-visible attachment/file as `file`. ChatGPT resolves this
        marked file parameter into a structured payload containing an authorized
        temporary download URL plus file metadata. Koba streams the bytes server-side;
        do not base64-encode chat attachments for this tool.

        Use artifact_upload_* only as the generic resumable fallback for clients that
        cannot provide a file-capable argument.
        """
        return ingest_file(
            file=file,
            name=name,
            mime_type=mime_type,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

    @mcp.tool(title="Artifact upload begin", annotations=write_annotations)
    def artifact_upload_begin(
        name: str,
        size_bytes: int,
        mime_type: str = "",
        expected_sha256: str = "",
    ) -> dict[str, Any]:
        """Create a resumable upload session for an agent-controlled file transfer."""
        return ArtifactUploadManager().begin(
            name=name,
            size_bytes=size_bytes,
            mime_type=mime_type,
            expected_sha256=expected_sha256,
        )

    @mcp.tool(title="Artifact upload status", annotations=read_annotations)
    def artifact_upload_status(upload_id: str) -> dict[str, Any]:
        """Return upload progress and the exact next byte offset."""
        return ArtifactUploadManager().status(upload_id)

    @mcp.tool(title="Artifact upload list", annotations=read_annotations)
    def artifact_upload_list(
        state: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List resumable upload sessions so agents can recover interrupted transfers."""
        return ArtifactUploadManager().list(state=state, offset=offset, limit=limit)

    @mcp.tool(title="Artifact upload write", annotations=write_annotations)
    def artifact_upload_write(
        upload_id: str,
        offset: int,
        data_base64: str,
    ) -> dict[str, Any]:
        """Append one base64-encoded chunk at the exact next offset.

        The server rejects oversized, reordered, sparse, or overlapping chunks.
        Use the returned next_offset for the following call.
        """
        return ArtifactUploadManager().write(upload_id, offset, data_base64)

    @mcp.tool(title="Artifact upload finish", annotations=write_annotations)
    def artifact_upload_finish(upload_id: str) -> dict[str, Any]:
        """Verify size/SHA-256, commit the upload, and return its immutable artifact_id."""
        return ArtifactUploadManager().finish(upload_id)

    @mcp.tool(title="Artifact upload cancel", annotations=destructive_annotations)
    def artifact_upload_cancel(upload_id: str) -> dict[str, Any]:
        """Cancel an unfinished upload and discard its staged bytes."""
        return ArtifactUploadManager().cancel(upload_id)

    @mcp.tool(title="Artifact upload cleanup", annotations=destructive_annotations)
    def artifact_upload_cleanup(
        older_than_hours: int = 24,
        dry_run: bool = True,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Preview or remove stale upload-session state without deleting committed artifacts."""
        return ArtifactUploadManager().cleanup(
            older_than_hours=older_than_hours,
            dry_run=dry_run,
            limit=limit,
        )

    @mcp.tool(title="Artifact list", annotations=read_annotations)
    def artifact_list(
        query: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List immutable artifacts by metadata. Physical filesystem paths are private."""
        return ArtifactStore().list(query=query, offset=offset, limit=limit)

    @mcp.tool(title="Artifact info", annotations=read_annotations)
    def artifact_info(artifact_id: str) -> dict[str, Any]:
        """Return metadata, aliases, collections, and consumer references."""
        return ArtifactStore().info(artifact_id)

    @mcp.tool(title="Artifact read", annotations=read_annotations)
    def artifact_read(
        artifact_id: str,
        offset: int = 0,
        length: int = 1024 * 1024,
    ) -> dict[str, Any]:
        """Read artifact bytes as base64 by immutable artifact_id."""
        return ArtifactStore().read(artifact_id, offset=offset, length=length)

    @mcp.tool(title="Artifact create text", annotations=write_annotations)
    def artifact_create_text(
        name: str,
        content: str,
        mime_type: str = "text/plain; charset=utf-8",
    ) -> dict[str, Any]:
        """Create an immutable text artifact generated by an agent or backend."""
        return ArtifactStore().put_text(name=name, content=content, mime_type=mime_type)

    @mcp.tool(title="Artifact extract", annotations=write_annotations)
    def artifact_extract(artifact_id: str) -> dict[str, Any]:
        """Extract a tar/zip artifact into a content-addressed collection."""
        return ArtifactStore().extract(artifact_id)

    @mcp.tool(title="Artifact collection list", annotations=read_annotations)
    def artifact_collection_list(
        collection_id: str,
        prefix: str = "",
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        """List files in an extracted collection without exposing server paths."""
        return ArtifactStore().collection_list(
            collection_id,
            prefix=prefix,
            offset=offset,
            limit=limit,
        )

    @mcp.tool(title="Artifact collection delete", annotations=destructive_annotations)
    def artifact_collection_delete(collection_id: str) -> dict[str, Any]:
        """Delete a collection manifest while leaving its immutable member artifacts intact."""
        return ArtifactStore().collection_delete(collection_id)

    @mcp.tool(title="Artifact collection resolve", annotations=read_annotations)
    def artifact_collection_resolve(
        collection_id: str,
        path: str,
    ) -> dict[str, Any]:
        """Resolve one collection-relative path to its immutable artifact_id."""
        return ArtifactStore().collection_resolve(collection_id, path)

    @mcp.tool(title="Artifact references", annotations=read_annotations)
    def artifact_references(
        consumer_type: str = "",
        consumer_id: str = "",
    ) -> dict[str, Any]:
        """List durable links from artifacts to consumers such as Ghidra projects."""
        refs = ArtifactStore().references(
            consumer_type=consumer_type,
            consumer_id=consumer_id,
        )
        return {"references": refs, "count": len(refs)}

    @mcp.tool(title="Artifact release reference", annotations=destructive_annotations)
    def artifact_release_reference(
        artifact_id: str,
        consumer_type: str,
        consumer_id: str,
        role: str = "source",
    ) -> dict[str, Any]:
        """Release one consumer reference so an unused artifact can later be collected."""
        return ArtifactStore().release_reference(
            artifact_id,
            consumer_type,
            consumer_id,
            role,
        )

    @mcp.tool(title="Artifact delete", annotations=destructive_annotations)
    def artifact_delete(
        artifact_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Delete an unreferenced artifact. force=true also removes its links."""
        return ArtifactStore().delete(artifact_id, force=force)

    @mcp.tool(title="Artifact garbage collect", annotations=destructive_annotations)
    def artifact_gc(
        dry_run: bool = True,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Find or delete artifacts that are not referenced by any consumer or collection."""
        return ArtifactStore().gc(dry_run=dry_run, limit=limit)
