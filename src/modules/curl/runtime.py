from __future__ import annotations

from common.runtime_annotations import READ_ONLY_LOCAL, WRITE_EXTERNAL
from common.runtime_common import build_private_mcp, private_http_app
from common.settings import CurlSettings, FileSettings, PrivateRuntimeSettings
from modules.files.file_store import FileStore

from .executor import resolve_curl_binary
from .tools import register_curl_tools

_private_settings = PrivateRuntimeSettings()
_file_settings = FileSettings()
_curl_settings = CurlSettings()

mcp = build_private_mcp("curl")
_store = FileStore(settings=_file_settings)
_curl_binary = resolve_curl_binary(_curl_settings)

register_curl_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_EXTERNAL,
    store=_store,
    curl_binary=_curl_binary,
)

app = private_http_app(mcp, _private_settings)
