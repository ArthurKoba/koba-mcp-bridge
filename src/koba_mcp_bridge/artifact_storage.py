from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import shutil
import socket
import stat
import tarfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastmcp import FastMCP

_DEFAULT_ROOT = "/artifacts"
_DEFAULT_MAX_CHUNK = 1024 * 1024
_DEFAULT_MAX_IMPORT = 8 * 1024 * 1024 * 1024
_DEFAULT_MAX_EXTRACT_FILES = 20_000
_DEFAULT_MAX_EXTRACT_BYTES = 16 * 1024 * 1024 * 1024
_STANDARD_DIRS = ("inbox", "exports", "scripts")


class ArtifactError(ValueError):
    pass


def _root() -> Path:
    raw = os.getenv("ARTIFACT_ROOT", _DEFAULT_ROOT).strip() or _DEFAULT_ROOT
    root = Path(raw)
    if not root.is_absolute():
        raise ArtifactError("ARTIFACT_ROOT must be an absolute path")
    return root.resolve(strict=False)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ArtifactError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ArtifactError(f"{name} must be between {minimum} and {maximum}")
    return value


def _max_chunk() -> int:
    return _env_int(
        "ARTIFACT_MAX_CHUNK_BYTES",
        _DEFAULT_MAX_CHUNK,
        4096,
        16 * 1024 * 1024,
    )


def _max_import_bytes() -> int:
    return _env_int(
        "ARTIFACT_MAX_IMPORT_BYTES",
        _DEFAULT_MAX_IMPORT,
        1024 * 1024,
        64 * 1024 * 1024 * 1024,
    )


def _max_extract_files() -> int:
    return _env_int(
        "ARTIFACT_MAX_EXTRACT_FILES",
        _DEFAULT_MAX_EXTRACT_FILES,
        1,
        100_000,
    )


def _max_extract_bytes() -> int:
    return _env_int(
        "ARTIFACT_MAX_EXTRACT_BYTES",
        _DEFAULT_MAX_EXTRACT_BYTES,
        1024 * 1024,
        128 * 1024 * 1024 * 1024,
    )


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
    stat_result = path.stat()
    result: dict[str, Any] = {
        "path": _rel(path),
        "type": "directory" if path.is_dir() else "file",
        "size_bytes": stat_result.st_size,
        "modified_at": datetime.fromtimestamp(stat_result.st_mtime, UTC).isoformat(),
    }
    if include_hash and path.is_file():
        result["sha256"] = _sha256(path)
    return result


def _validate_https_source(source: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(source)
    if parsed.scheme.casefold() != "https":
        raise ArtifactError("source must be an HTTPS URL")
    if not parsed.hostname:
        raise ArtifactError("source URL has no hostname")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ArtifactError("source hostname cannot be resolved") from exc

    if not addresses:
        raise ArtifactError("source hostname cannot be resolved")

    for item in addresses:
        raw_ip = str(item[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise ArtifactError("source hostname resolved to an invalid address") from exc
        if not address.is_global:
            raise ArtifactError("source URL resolves to a non-public address")
    return parsed


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        _validate_https_source(str(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_https_source(request: urllib.request.Request):
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    return opener.open(request, timeout=60)


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
    page = all_entries[offset : offset + limit]
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
            raise ArtifactError(
                f"offset mismatch: current size is {current}, requested {offset}"
            )
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


def artifact_import_file_impl(
    source: str,
    path: str,
    overwrite: bool = False,
    expected_sha256: str = "",
    max_bytes: int = 0,
) -> dict[str, Any]:
    ensure_artifact_layout()
    _validate_https_source(source)
    target = _resolve(path)
    if target.exists() and not overwrite:
        raise ArtifactError("artifact already exists")
    target.parent.mkdir(parents=True, exist_ok=True)

    configured_limit = _max_import_bytes()
    limit = configured_limit if max_bytes == 0 else max_bytes
    if limit <= 0 or limit > configured_limit:
        raise ArtifactError(f"max_bytes must be between 1 and {configured_limit}")

    expected = expected_sha256.strip().casefold()
    if expected and (
        len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ArtifactError("expected_sha256 must be a 64-character hexadecimal digest")

    request = urllib.request.Request(
        source,
        headers={"User-Agent": "koba-mcp-bridge/0.1 artifact-import"},
    )
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    digest = hashlib.sha256()
    total = 0

    try:
        try:
            response = _open_https_source(request)
        except Exception as exc:
            raise ArtifactError(f"source download failed: {type(exc).__name__}") from exc

        with response:
            final_url = str(response.geturl())
            _validate_https_source(final_url)
            header_length = response.headers.get("Content-Length")
            if header_length:
                try:
                    declared_size = int(header_length)
                except ValueError:
                    declared_size = -1
                if declared_size > limit:
                    raise ArtifactError("source exceeds configured import size limit")

            with temp.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise ArtifactError("source exceeds configured import size limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        actual = digest.hexdigest()
        if expected and actual != expected:
            raise ArtifactError(
                f"source SHA-256 mismatch: expected {expected}, found {actual}"
            )
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()

    parsed = urllib.parse.urlsplit(source)
    return {
        "success": True,
        "source_host": parsed.hostname,
        **_meta(target, include_hash=True),
    }


def _safe_archive_relative(name: str) -> PurePosixPath:
    value = name.replace("\\", "/")
    rel = PurePosixPath(value)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise ArtifactError(f"archive member escapes destination: {name}")
    cleaned = PurePosixPath(*(part for part in rel.parts if part not in {"", "."}))
    if not cleaned.parts:
        raise ArtifactError("archive member has an empty path")
    return cleaned


def _archive_output(destination: Path, member_name: str) -> Path:
    rel = _safe_archive_relative(member_name)
    candidate = (destination / rel.as_posix()).resolve(strict=False)
    try:
        candidate.relative_to(destination)
    except ValueError as exc:
        raise ArtifactError(f"archive member escapes destination: {member_name}") from exc
    return candidate


def _extract_tar(
    archive: Path,
    destination: Path,
    max_files: int,
    max_total_bytes: int,
) -> tuple[int, int, int]:
    files = 0
    directories = 0
    total_bytes = 0

    with tarfile.open(archive, mode="r:*") as handle:
        members = handle.getmembers()
        for member in members:
            _archive_output(destination, member.name)
            if member.isdir():
                directories += 1
                continue
            if not member.isfile():
                raise ArtifactError(f"unsupported archive member type: {member.name}")
            files += 1
            total_bytes += member.size
            if files > max_files:
                raise ArtifactError("archive exceeds configured file-count limit")
            if total_bytes > max_total_bytes:
                raise ArtifactError("archive exceeds configured extraction size limit")

        for member in members:
            output = _archive_output(destination, member.name)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            source = handle.extractfile(member)
            if source is None:
                raise ArtifactError(f"unable to read archive member: {member.name}")
            with source, output.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)

    return files, directories, total_bytes


def _extract_zip(
    archive: Path,
    destination: Path,
    max_files: int,
    max_total_bytes: int,
) -> tuple[int, int, int]:
    files = 0
    directories = 0
    total_bytes = 0

    with zipfile.ZipFile(archive) as handle:
        members = handle.infolist()
        for member in members:
            _archive_output(destination, member.filename)
            mode = (member.external_attr >> 16) & 0o170000
            if mode and stat.S_ISLNK(mode):
                raise ArtifactError(f"archive symlink is not allowed: {member.filename}")
            if member.is_dir():
                directories += 1
                continue
            if mode and not stat.S_ISREG(mode):
                raise ArtifactError(
                    f"unsupported archive member type: {member.filename}"
                )
            files += 1
            total_bytes += member.file_size
            if files > max_files:
                raise ArtifactError("archive exceeds configured file-count limit")
            if total_bytes > max_total_bytes:
                raise ArtifactError("archive exceeds configured extraction size limit")

        for member in members:
            output = _archive_output(destination, member.filename)
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(member, "r") as source, output.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)

    return files, directories, total_bytes


def artifact_extract_archive_impl(
    archive_path: str,
    destination: str,
    max_files: int = 0,
    max_total_bytes: int = 0,
) -> dict[str, Any]:
    archive = _resolve(archive_path)
    if not archive.is_file():
        raise ArtifactError("archive_path is not a file")

    target = _resolve(destination)
    if target.exists():
        raise ArtifactError("destination already exists")

    configured_files = _max_extract_files()
    configured_bytes = _max_extract_bytes()
    file_limit = configured_files if max_files == 0 else max_files
    byte_limit = configured_bytes if max_total_bytes == 0 else max_total_bytes
    if file_limit <= 0 or file_limit > configured_files:
        raise ArtifactError(f"max_files must be between 1 and {configured_files}")
    if byte_limit <= 0 or byte_limit > configured_bytes:
        raise ArtifactError(
            f"max_total_bytes must be between 1 and {configured_bytes}"
        )

    target.mkdir(parents=True)
    try:
        lower = archive.name.casefold()
        supported_tar = (
            ".tar",
            ".tar.gz",
            ".tgz",
            ".tar.bz2",
            ".tbz2",
            ".tar.xz",
        )
        if lower.endswith(supported_tar):
            files, directories, total_bytes = _extract_tar(
                archive,
                target,
                file_limit,
                byte_limit,
            )
        elif lower.endswith(".zip"):
            files, directories, total_bytes = _extract_zip(
                archive,
                target,
                file_limit,
                byte_limit,
            )
        else:
            raise ArtifactError(
                "supported archives: .tar, .tar.gz, .tgz, .tar.bz2, .tar.xz, .zip"
            )
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    top_level = sorted(item.name for item in target.iterdir())
    return {
        "success": True,
        "archive_path": _rel(archive),
        "destination": _rel(target),
        "files": files,
        "directories": directories,
        "total_bytes": total_bytes,
        "top_level": top_level[:200],
        "top_level_truncated": len(top_level) > 200,
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
            "max_import_bytes": _max_import_bytes(),
            "max_extract_files": _max_extract_files(),
            "max_extract_bytes": _max_extract_bytes(),
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

        This is the low-level fallback for clients that cannot provide a retrievable
        attachment URL. Prefer artifact_import_file for chat or client attachments.
        """
        ensure_artifact_layout()
        return artifact_upload_chunk_impl(path, data_base64, offset, truncate)

    @mcp.tool(title="Artifact import file", annotations=write_annotations)
    def artifact_import_file(
        source: str,
        path: str,
        overwrite: bool = False,
        expected_sha256: str = "",
        max_bytes: int = 0,
    ) -> dict[str, Any]:
        """Stage one client/chat attachment in Koba artifact storage.

        Pass the attachment or file argument as source. File-capable MCP clients may
        translate a client-local attachment path to a temporary HTTPS URL before
        invoking this tool. The Koba server downloads the bytes directly into the
        relative artifact path; a client-local /mnt path is never a Koba path.
        """
        return artifact_import_file_impl(
            source,
            path,
            overwrite,
            expected_sha256,
            max_bytes,
        )

    @mcp.tool(title="Artifact extract archive", annotations=write_annotations)
    def artifact_extract_archive(
        archive_path: str,
        destination: str,
        max_files: int = 0,
        max_total_bytes: int = 0,
    ) -> dict[str, Any]:
        """Extract a staged archive on Koba into a new artifact directory.

        Supports tar/tar.gz/tgz/tar.bz2/tar.xz/zip. Symlinks, hard links, devices,
        path traversal, and extraction outside ARTIFACT_ROOT are rejected.
        """
        return artifact_extract_archive_impl(
            archive_path,
            destination,
            max_files,
            max_total_bytes,
        )

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
