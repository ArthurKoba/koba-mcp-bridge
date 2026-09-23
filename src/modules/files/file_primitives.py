from __future__ import annotations

import mimetypes
from datetime import UTC, datetime
from pathlib import PurePosixPath

_DEFAULT_READ_CHUNK = 1024 * 1024


class FileError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_file_id(file_id: str) -> tuple[str, str]:
    value = file_id.strip().casefold()
    if not value.startswith("sha256:"):
        raise FileError("file_id must use the sha256:<digest> form")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise FileError("file_id contains an invalid SHA-256 digest")
    return value, digest


def safe_collection_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise FileError(f"unsafe archive path: {path}")
    cleaned = PurePosixPath(*(part for part in candidate.parts if part not in {"", "."}))
    if not cleaned.parts:
        raise FileError("archive member path is empty")
    return cleaned.as_posix()


def guess_mime(name: str, supplied: str = "") -> str:
    if supplied.strip():
        return supplied.strip()
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def size_display(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
