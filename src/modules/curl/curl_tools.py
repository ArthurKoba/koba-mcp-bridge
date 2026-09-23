"""Compatibility facade for the structured curl implementation."""

from __future__ import annotations

from .errors import CurlError
from .operations import curl_download_impl, curl_request_impl, curl_stream_capture_impl
from .presets import DEFAULT_CURL_PRESET, curl_presets_impl
from .response import _curl_failure_diagnostic, _http_status_diagnostic

__all__ = [
    "DEFAULT_CURL_PRESET",
    "CurlError",
    "_curl_failure_diagnostic",
    "_http_status_diagnostic",
    "curl_download_impl",
    "curl_presets_impl",
    "curl_request_impl",
    "curl_stream_capture_impl",
]
