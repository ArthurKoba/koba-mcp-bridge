from __future__ import annotations

from modules.files.file_store import FileStore
from modules.files.store_collections import FileCollectionStore
from modules.files.store_core import FileStoreCore
from modules.files.store_lifecycle import FileLifecycleStore
from modules.files.store_metadata import FileMetadataStore
from modules.files.store_references import FileReferenceStore


def test_file_store_facade_composes_focused_storage_layers() -> None:
    assert FileStore.__bases__ == (FileLifecycleStore,)
    assert FileLifecycleStore.__bases__ == (FileCollectionStore,)
    assert FileCollectionStore.__bases__ == (FileReferenceStore,)
    assert FileReferenceStore.__bases__ == (FileMetadataStore,)
    assert FileMetadataStore.__bases__ == (FileStoreCore,)


def test_file_store_methods_have_single_capability_owner() -> None:
    assert "put_stream" in FileStoreCore.__dict__
    assert "info" in FileMetadataStore.__dict__
    assert "add_reference" in FileReferenceStore.__dict__
    assert "extract" in FileCollectionStore.__dict__
    assert "delete" in FileLifecycleStore.__dict__

    assert "put_stream" not in FileStore.__dict__
    assert "info" not in FileStore.__dict__
    assert "add_reference" not in FileStore.__dict__
    assert "extract" not in FileStore.__dict__
    assert "delete" not in FileStore.__dict__
