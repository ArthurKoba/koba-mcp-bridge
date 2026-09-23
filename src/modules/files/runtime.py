from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_LOCAL,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
)
from common.runtime_common import build_private_mcp, private_http_app
from common.settings import FileSettings, PrivateRuntimeSettings

from .file_store import FileStore
from .file_tools import register_file_tools
from .upload_manager import FileUploadManager

_private_settings = PrivateRuntimeSettings()
_file_settings = FileSettings()

mcp = build_private_mcp("files")
_store = FileStore(settings=_file_settings)
_upload_manager = FileUploadManager(_store)

register_file_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
    DESTRUCTIVE_LOCAL,
    store=_store,
    upload_manager=_upload_manager,
)

app = private_http_app(mcp, _private_settings)
