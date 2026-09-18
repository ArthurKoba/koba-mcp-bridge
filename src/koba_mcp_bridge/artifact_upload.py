from __future__ import annotations

import base64
from typing import Any

from fastmcp.apps.file_upload import FileUpload

from .artifact_store import ArtifactError, ArtifactStore, upload_max_bytes


class ArtifactUpload(FileUpload):
    """Browser-native file ingress backed by the persistent Koba artifact store."""

    def __init__(self) -> None:
        super().__init__(
            name="Koba Files",
            max_file_size=upload_max_bytes(),
            title="Upload files to Koba",
            description=(
                "Files are stored as immutable content-addressed artifacts and can be "
                "used by Ghidra or any other Koba backend."
            ),
            drop_label="Drop files here",
        )

    def _get_scope_key(self, ctx) -> str:
        # OAuth already gates the bridge. The object store is intentionally shared
        # across authenticated Koba workflows and deduplicates by SHA-256.
        return "__koba_artifacts__"

    def on_store(self, files: list[dict[str, Any]], ctx) -> list[dict[str, Any]]:
        del ctx
        store = ArtifactStore()
        store.ensure()
        for file in files:
            try:
                payload = base64.b64decode(str(file.get("data", "")), validate=True)
            except Exception as exc:
                raise ArtifactError("uploaded file contains invalid base64 data") from exc
            declared = int(file.get("size", len(payload)))
            if declared != len(payload):
                raise ArtifactError("uploaded file size does not match payload")
            store.put_bytes(
                payload,
                name=str(file.get("name", "upload.bin")) or "upload.bin",
                mime_type=str(file.get("type", "")),
                source="browser-upload",
            )
        return self.on_list(None)

    def on_list(self, ctx) -> list[dict[str, Any]]:
        del ctx
        result = ArtifactStore().list(limit=500)
        return [
            {
                "name": item["name"],
                "type": item["mime_type"],
                "size": item["size_bytes"],
                "size_display": item["size_display"],
                "uploaded_at": item["created_at"],
                "artifact_id": item["artifact_id"],
            }
            for item in result["items"]
        ]

    def on_read(self, name: str, ctx) -> dict[str, Any]:
        del ctx
        store = ArtifactStore()
        info = store.info(name) if name.startswith("sha256:") else store.find_by_name(name)
        path = store.path_for(str(info["artifact_id"]))
        preview_limit = 256 * 1024
        data = path.read_bytes()[:preview_limit]
        result = {
            "name": info["name"],
            "type": info["mime_type"],
            "size": info["size_bytes"],
            "uploaded_at": info["created_at"],
            "artifact_id": info["artifact_id"],
            "truncated": info["size_bytes"] > preview_limit,
        }
        if str(info["mime_type"]).startswith("text/"):
            result["content"] = data.decode("utf-8", errors="replace")
        else:
            result["content_base64"] = base64.b64encode(data).decode("ascii")
        return result
