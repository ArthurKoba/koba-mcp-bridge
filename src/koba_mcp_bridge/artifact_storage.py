from __future__ import annotations

import base64
import hashlib
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

_DEFAULT_ROOT = "/artifacts"
_DEFAULT_MAX_CHUNK = 1024 * 1024
_STANDARD_DIRS = ("inbox", "exports", "scripts")


class ArtifactError(ValueError):
    pass


def _root() -> Path:
    raw = os.getenv("ARTIFACT_ROOT", _DEFAULT_ROOT).strip() or _DEFAULT_ROOT
    root = Path(raw)
    if not root.is_absolute():
        raise ArtifactError("ARTIFACT_ROOT must be an absolute path")
    return root.resolve(strict=False)


def _max_chunk() -> int:
    raw = os.getenv("ARTIFACT_MAX_CHUNK_BYTES", str(_DEFAULT_MAX_CHUNK)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ArtifactError("ARTIFACT_MAX_CHUNK_BYTES must be an integer") from exc
    if value < 4096 or value > 16 * 1024 * 1024:
        raise ArtifactError("ARTIFACT_MAX_CHUNK_BYTES must be between 4096 and 16777216")
    return value


def _resolve(path: str, *, allow_root: bool = False) -> Path:
    value = str(path or "").strip().replace("\\", "/")
    if value.startswith("/"):
        raise ArtifactError("artifact path must be relative")
    root = _root()
    candidate = (root / value).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ArtifactError("artifact path escapes storage root") from exc
    if candidate == root and not allow_root:
        raise ArtifactError("artifact path must name an item")
    return candidate


def _rel(path: Path) -> str:
    root = _root()
    return "" if path == root else path.relative_to(root).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _meta(path: Path, *, include_hash: bool = False) -> dict[str, Any]:
    stat = path.stat()
    result: dict[str, Any] = {
        "path": _rel(path),
        "type": "directory" if path.is_dir() else "file",
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }
    if include_hash and path.is_file():
        result["sha256"] = _sha256(path)
    return result


def ensure_artifact_layout() -> None:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    for name in _STANDARD_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)


def artifact_list_impl(path: str = "", offset: int = 0, limit: int = 200) -> dict[str, Any]:
    if offset < 0:
        raise ArtifactError("offset must be non-negative")
    if limit <= 0 or limit > 1000:
        raise ArtifactError("limit must be between 1 and 1000")
    target = _resolve(path, allow_root=True)
    if not target.is_dir():
        raise ArtifactError("artifact path is not a directory")
    all_entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
    page = all_entries[offset: offset + limit]
    return {
        "path": _rel(target),
        "entries": [_meta(item) for item in page],
        "offset": offset,
        "limit": limit,
        "total": len(all_entries),
        "truncated": offset + len(page) < len(all_entries),
    }


def artifact_info_impl(path: str, sha256: bool = True) -> dict[str, Any]:
    target = _resolve(path)
    if not target.exists():
        raise ArtifactError("artifact does not exist")
    return _meta(target, include_hash=sha256)


def artifact_write_text_impl(path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise ArtifactError("artifact already exists")
    encoded = content.encode("utf-8")
    if len(encoded) > _max_chunk():
        raise ArtifactError("text exceeds chunk limit; use artifact_upload_chunk")
    target.write_bytes(encoded)
    return {"success": True, **_meta(target, include_hash=True)}


def artifact_upload_chunk_impl(
    path: str,
    data_base64: str,
    offset: int = 0,
    truncate: bool = False,
) -> dict[str, Any]:
    if offset < 0:
        raise ArtifactError("offset must be non-negative")
    if truncate and offset != 0:
        raise ArtifactError("truncate=true requires offset=0")
    try:
        payload = base64.b64decode(data_base64, validate=True)
    except Exception as exc:
        raise ArtifactError("data_base64 is not valid base64") from exc
    limit = _max_chunk()
    if len(payload) > limit:
        raise ArtifactError(f"decoded chunk exceeds {limit} bytes")
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if truncate:
        mode = "wb"
    else:
        current = target.stat().st_size if target.exists() else 0
        if current != offset:
            raise ArtifactError(f"offset mismatch: current size is {current}, requested {offset}")
        mode = "ab"
    with target.open(mode) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    size = target.stat().st_size
    return {
        "success": True,
        "path": _rel(target),
        "bytes_written": len(payload),
        "size_bytes": size,
        "next_offset": size,
    }


def artifact_download_chunk_impl(
    path: str,
    offset: int = 0,
    length: int = _DEFAULT_MAX_CHUNK,
) -> dict[str, Any]:
    if offset < 0:
        raise ArtifactError("offset must be non-negative")
    limit = _max_chunk()
    if length <= 0 or length > limit:
        raise ArtifactError(f"length must be between 1 and {limit}")
    target = _resolve(path)
    if not target.is_file():
        raise ArtifactError("artifact is not a file")
    size = target.stat().st_size
    if offset > size:
        raise ArtifactError("offset exceeds artifact size")
    with target.open("rb") as handle:
        handle.seek(offset)
        payload = handle.read(length)
    next_offset = offset + len(payload)
    return {
        "path": _rel(target),
        "offset": offset,
        "bytes_read": len(payload),
        "next_offset": next_offset,
        "size_bytes": size,
        "eof": next_offset >= size,
        "data_base64": base64.b64encode(payload).decode("ascii"),
    }


def artifact_delete_impl(path: str, recursive: bool = False) -> dict[str, Any]:
    target = _resolve(path)
    if not target.exists():
        return {"success": True, "path": _rel(target), "already_absent": True}
    rel = _rel(target)
    if rel in _STANDARD_DIRS:
        raise ArtifactError("standard artifact directories cannot be deleted")
    if target.is_dir():
        if not recursive:
            raise ArtifactError("directory deletion requires recursive=true")
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"success": True, "path": rel, "deleted": True}


def register_artifact_tools(
    mcp: FastMCP,
    read_annotations: Any,
    write_annotations: Any,
    destructive_annotations: Any,
) -> None:

    @mcp.tool(title="Artifact storage status", annotations=read_annotations)
    def artifact_status() -> dict[str, Any]:
        """Inspect shared artifact storage used by infrastructure backends."""
        ensure_artifact_layout()
        root = _root()
        usage = shutil.disk_usage(root)
        return {
            "status": "ok",
            "standard_directories": list(_STANDARD_DIRS),
            "max_chunk_bytes": _max_chunk(),
            "free_bytes": usage.free,
        }

    @mcp.tool(title="Artifact list", annotations=read_annotations)
    def artifact_list(path: str = "", offset: int = 0, limit: int = 200) -> dict[str, Any]:
        """List files/directories below a relative artifact path with pagination."""
        ensure_artifact_layout()
        return artifact_list_impl(path, offset, limit)

    @mcp.tool(title="Artifact info", annotations=read_annotations)
    def artifact_info(path: str, sha256: bool = True) -> dict[str, Any]:
        """Read artifact metadata and optionally calculate SHA-256."""
        return artifact_info_impl(path, sha256)

    @mcp.tool(title="Artifact mkdir", annotations=write_annotations)
    def artifact_mkdir(path: str) -> dict[str, Any]:
        """Create a directory recursively inside artifact storage."""
        ensure_artifact_layout()
        target = _resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise ArtifactError("artifact path exists and is not a directory")
        return {"success": True, **_meta(target)}

    @mcp.tool(title="Artifact write text", annotations=write_annotations)
    def artifact_write_text(path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
        """Write UTF-8 text, primarily for scripts/manifests produced by an agent."""
        ensure_artifact_layout()
        return artifact_write_text_impl(path, content, overwrite)

    @mcp.tool(title="Artifact upload chunk", annotations=write_annotations)
    def artifact_upload_chunk(
        path: str,
        data_base64: str,
        offset: int = 0,
        truncate: bool = False,
    ) -> dict[str, Any]:
        """Upload one sequential base64 chunk.

        Start with offset=0 and truncate=true. Each next call must use the
        returned next_offset, which prevents sparse or accidentally reordered writes.
        """
        ensure_artifact_layout()
        return artifact_upload_chunk_impl(path, data_base64, offset, truncate)

    @mcp.tool(title="Artifact download chunk", annotations=read_annotations)
    def artifact_download_chunk(
        path: str,
        offset: int = 0,
        length: int = _DEFAULT_MAX_CHUNK,
    ) -> dict[str, Any]:
        """Download one artifact chunk as base64."""
        return artifact_download_chunk_impl(path, offset, length)

    @mcp.tool(title="Artifact delete", annotations=destructive_annotations)
    def artifact_delete(path: str, recursive: bool = False) -> dict[str, Any]:
        """Delete one artifact file, or a directory when recursive=true."""
        return artifact_delete_impl(path, recursive)
