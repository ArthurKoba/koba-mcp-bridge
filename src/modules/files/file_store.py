from __future__ import annotations

from .file_primitives import (
    FileError,
    max_extract_bytes,
    max_extract_files,
    upload_max_bytes,
)
from .store_lifecycle import FileLifecycleStore


class FileStore(FileLifecycleStore):
    """Persistent immutable file store assembled from focused storage capabilities."""


__all__ = [
    "FileError",
    "FileStore",
    "max_extract_bytes",
    "max_extract_files",
    "upload_max_bytes",
]
