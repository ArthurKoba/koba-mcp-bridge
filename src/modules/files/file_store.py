from __future__ import annotations

from .file_primitives import FileError
from .store_lifecycle import FileLifecycleStore


class FileStore(FileLifecycleStore):
    """Persistent immutable file store assembled from focused storage capabilities."""


__all__ = ["FileError", "FileStore"]
