from __future__ import annotations

import uuid

from .file_store import FileError


def normalize_upload_id(upload_id: str) -> str:
    value = upload_id.strip().casefold()
    if not value.startswith("upload:"):
        raise FileError("upload_id must use the upload:<uuid> form")
    raw = value.removeprefix("upload:")
    try:
        parsed = uuid.UUID(raw)
    except ValueError as exc:
        raise FileError("upload_id contains an invalid UUID") from exc
    return f"upload:{parsed}"


def validate_file_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise FileError("name must not be empty")
    if len(value) > 255:
        raise FileError("name must not exceed 255 characters")
    if "/" in value or "\\" in value or any(ord(ch) < 32 for ch in value):
        raise FileError("name must be a plain file name without path separators")
    return value


def validate_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if not digest:
        return ""
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise FileError("expected_sha256 must be a 64-character hexadecimal digest")
    return digest

