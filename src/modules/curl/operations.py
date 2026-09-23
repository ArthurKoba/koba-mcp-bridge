from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from common.models import JsonObject, JsonValue, json_value
from modules.files.file_store import FileStore, upload_max_bytes

from .errors import CurlError
from .executor import _build_curl_command, _execute_curl, _metadata_from_stdout
from .presets import DEFAULT_CURL_PRESET
from .request import (
    _body_source,
    _has_sensitive_redirect_state,
    _merged_headers,
    _validate_method,
    _validate_url,
    _with_query,
)
from .response import (
    _content_type,
    _curl_failure_diagnostic,
    _header_blocks_json,
    _header_fields_json,
    _header_values,
    _http_result,
    _http_status_diagnostic,
    _json_int,
    _parse_header_blocks,
    _preview,
    _response_filename,
)

_DEFAULT_PREVIEW_BYTES = 4096
_DEFAULT_REQUEST_MAX_BYTES = 2 * 1024 * 1024
_MAX_REQUEST_MAX_BYTES = 16 * 1024 * 1024
_DEFAULT_DOWNLOAD_MAX_BYTES = 1024 * 1024 * 1024
_MAX_DURATION_SECONDS = 300

def curl_request_impl(
    url: str,
    method: str = "GET",
    query: JsonObject | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    body_text: str | None = None,
    body_json: JsonObject | list[JsonValue] | None = None,
    body_form: JsonObject | None = None,
    body_base64: str | None = None,
    body_file_id: str | None = None,
    body_content_type: str = "",
    preset: str = DEFAULT_CURL_PRESET,
    follow_redirects: bool = True,
    max_redirects: int = 10,
    timeout_seconds: float = 60,
    connect_timeout_seconds: float = 15,
    verify_tls: bool = True,
    proxy_url: str = "",
    max_response_bytes: int = _DEFAULT_REQUEST_MAX_BYTES,
    forward_sensitive_headers_on_redirect: bool = False,
    preview_bytes: int = _DEFAULT_PREVIEW_BYTES,
) -> JsonObject:
    if max_response_bytes > _MAX_REQUEST_MAX_BYTES:
        raise CurlError(
            f"curl_request max_response_bytes may not exceed {_MAX_REQUEST_MAX_BYTES}; "
            "use curl_download for larger responses"
        )
    metadata, header_path, output_path = _execute_curl(
        method=method,
        url=url,
        query=query,
        headers=headers,
        cookies=cookies,
        body_text=body_text,
        body_json=body_json,
        body_form=body_form,
        body_base64=body_base64,
        body_file_id=body_file_id,
        body_content_type=body_content_type,
        preset=preset,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        verify_tls=verify_tls,
        proxy_url=proxy_url,
        max_response_bytes=max_response_bytes,
        forward_sensitive_headers_on_redirect=forward_sensitive_headers_on_redirect,
    )
    try:
        return _http_result(
            metadata=metadata,
            header_path=header_path,
            output_path=output_path,
            response_max_bytes=max_response_bytes,
            preview_bytes=preview_bytes,
        )
    finally:
        header_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

def curl_download_impl(
    url: str,
    method: str = "GET",
    query: JsonObject | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    body_text: str | None = None,
    body_json: JsonObject | list[JsonValue] | None = None,
    body_form: JsonObject | None = None,
    body_base64: str | None = None,
    body_file_id: str | None = None,
    body_content_type: str = "",
    file_name: str = "",
    preset: str = DEFAULT_CURL_PRESET,
    follow_redirects: bool = True,
    max_redirects: int = 10,
    timeout_seconds: float = 300,
    connect_timeout_seconds: float = 15,
    verify_tls: bool = True,
    proxy_url: str = "",
    max_bytes: int = _DEFAULT_DOWNLOAD_MAX_BYTES,
    store_http_errors: bool = False,
    forward_sensitive_headers_on_redirect: bool = False,
    preview_bytes: int = _DEFAULT_PREVIEW_BYTES,
) -> JsonObject:
    metadata, header_path, output_path = _execute_curl(
        method=method,
        url=url,
        query=query,
        headers=headers,
        cookies=cookies,
        body_text=body_text,
        body_json=body_json,
        body_form=body_form,
        body_base64=body_base64,
        body_file_id=body_file_id,
        body_content_type=body_content_type,
        preset=preset,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        verify_tls=verify_tls,
        proxy_url=proxy_url,
        max_response_bytes=max_bytes,
        forward_sensitive_headers_on_redirect=forward_sensitive_headers_on_redirect,
    )
    blocks = _parse_header_blocks(header_path)
    final_block = blocks[-1] if blocks else None
    status = _json_int(
        metadata.get("http_code"),
        default=final_block.status if final_block else 0,
        field="http_code",
    )
    final_url = str(metadata.get("url_effective") or metadata.get("request_url") or "")
    exit_code = _json_int(metadata.get("curl_exit_code"), field="curl_exit_code")
    try:
        if exit_code != 0:
            diagnostic = _curl_failure_diagnostic(
                exit_code,
                str(metadata.get("curl_error") or ""),
                metadata,
            )
            detail = (
                f"{diagnostic['error_type']}: {diagnostic['error_hint']}"
                if diagnostic is not None
                else f"curl exit code {exit_code}"
            )
            raise CurlError(f"curl download failed: {detail}")
        if not store_http_errors and not (200 <= status < 400):
            diagnostic = _http_status_diagnostic(status)
            hint = diagnostic["error_hint"] if diagnostic else f"HTTP {status}"
            raise CurlError(
                f"HTTP response was not stored as a file: {hint}"
            )
        size = output_path.stat().st_size
        if size > max_bytes:
            raise CurlError("download exceeded max_bytes")
        name = _response_filename(
            file_name,
            final_url,
            final_block,
            "download.bin",
        )
        ctype = _content_type(final_block, metadata)
        store = FileStore()
        file = store.put_file(
            output_path,
            name=name,
            mime_type=ctype,
            source="curl-download",
            consume=True,
        )
        with store.path_for(str(file["file_id"])).open("rb") as handle:
            data = handle.read(max(0, min(preview_bytes, 64 * 1024)))
        return {
            "status": status,
            "ok": 200 <= status < 400,
            "final_url": final_url,
            "redirect_count": _json_int(
                metadata.get("num_redirects"),
                default=max(0, len(blocks) - 1),
                field="num_redirects",
            ),
            "response_chain": _header_blocks_json(blocks),
            "response_headers": _header_fields_json(final_block),
            "set_cookies": json_value(_header_values(final_block, "Set-Cookie")),
            "content_type": ctype,
            "file": file,
            "curl_exit_code": exit_code,
            "curl_error": str(metadata.get("curl_error") or ""),
            **_preview(data, final_block, metadata, preview_bytes),
        }
    finally:
        header_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

def curl_stream_capture_impl(
    url: str,
    method: str = "GET",
    query: JsonObject | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    body_text: str | None = None,
    body_json: JsonObject | list[JsonValue] | None = None,
    body_form: JsonObject | None = None,
    body_base64: str | None = None,
    body_file_id: str | None = None,
    body_content_type: str = "",
    file_name: str = "",
    preset: str = DEFAULT_CURL_PRESET,
    follow_redirects: bool = True,
    max_redirects: int = 10,
    duration_seconds: float = 15,
    connect_timeout_seconds: float = 15,
    verify_tls: bool = True,
    proxy_url: str = "",
    max_bytes: int = 16 * 1024 * 1024,
    forward_sensitive_headers_on_redirect: bool = False,
    preview_bytes: int = _DEFAULT_PREVIEW_BYTES,
) -> JsonObject:
    if duration_seconds <= 0 or duration_seconds > _MAX_DURATION_SECONDS:
        raise CurlError(
            f"duration_seconds must be greater than 0 and at most {_MAX_DURATION_SECONDS}"
        )
    if max_bytes <= 0 or max_bytes > upload_max_bytes():
        raise CurlError(f"max_bytes must be between 1 and {upload_max_bytes()}")

    store = FileStore()
    store.ensure()
    clean_method = _validate_method(method)
    request_url = _with_query(_validate_url(url), query)
    merged = _merged_headers(preset, headers)
    body_path, temporary_body = _body_source(
        body_text=body_text,
        body_json=body_json,
        body_form=body_form,
        body_base64=body_base64,
        body_file_id=body_file_id,
        body_content_type=body_content_type,
        headers=merged,
        store=store,
    )

    fd_headers, raw_headers = tempfile.mkstemp(
        prefix="curl-stream-headers-", dir=store.tmp
    )
    os.close(fd_headers)
    header_path = Path(raw_headers)
    fd_output, raw_output = tempfile.mkstemp(
        prefix="curl-stream-output-", dir=store.tmp
    )
    os.close(fd_output)
    output_path = Path(raw_output)

    sensitive_redirect_state = _has_sensitive_redirect_state(merged, cookies)
    effective_follow_redirects = follow_redirects and (
        forward_sensitive_headers_on_redirect or not sensitive_redirect_state
    )

    command = _build_curl_command(
        method=clean_method,
        url=request_url,
        headers=merged,
        cookies=cookies,
        body_path=body_path,
        follow_redirects=effective_follow_redirects,
        max_redirects=max_redirects if effective_follow_redirects else 0,
        timeout_seconds=duration_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        verify_tls=verify_tls,
        proxy_url=proxy_url,
        header_path=header_path,
        output_path=output_path,
        max_response_bytes=max_bytes,
    )

    started = time.monotonic()
    stop_reason = "curl_exit"
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        while proc.poll() is None:
            elapsed = time.monotonic() - started
            size = output_path.stat().st_size if output_path.exists() else 0
            if size >= max_bytes:
                stop_reason = "max_bytes"
                proc.terminate()
                break
            if elapsed >= duration_seconds:
                stop_reason = "duration"
                proc.terminate()
                break
            time.sleep(0.1)

        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=3)
            if stop_reason == "curl_exit":
                stop_reason = "forced_kill"
    finally:
        if temporary_body is not None:
            temporary_body.unlink(missing_ok=True)

    elapsed_seconds = round(time.monotonic() - started, 3)
    metadata = _metadata_from_stdout(stdout)
    metadata["curl_exit_code"] = int(proc.returncode or 0)
    metadata["curl_error"] = stderr.strip()
    blocks = _parse_header_blocks(header_path)
    final_block = blocks[-1] if blocks else None
    status = _json_int(
        metadata.get("http_code"),
        default=final_block.status if final_block else 0,
        field="http_code",
    )
    final_url = str(metadata.get("url_effective") or request_url)
    size = output_path.stat().st_size if output_path.exists() else 0

    if proc.returncode == 0 and stop_reason == "curl_exit":
        stop_reason = "eof"
    elif proc.returncode == 28 and stop_reason == "curl_exit":
        stop_reason = "duration"
    elif proc.returncode == 63 and stop_reason == "curl_exit":
        stop_reason = "max_bytes"
    elif proc.returncode not in (0, 28, 63) and stop_reason == "curl_exit":
        stop_reason = "curl_error"

    try:
        name = _response_filename(
            file_name,
            final_url,
            final_block,
            "stream-capture.bin",
        )
        ctype = _content_type(final_block, metadata)
        file = store.put_file(
            output_path,
            name=name,
            mime_type=ctype,
            source="curl-stream-capture",
            consume=True,
        )
        with store.path_for(str(file["file_id"])).open("rb") as handle:
            data = handle.read(max(0, min(preview_bytes, 64 * 1024)))
        return {
            "status": status,
            "final_url": final_url,
            "stop_reason": stop_reason,
            "elapsed_seconds": elapsed_seconds,
            "captured_bytes": size,
            "max_bytes": max_bytes,
            "duration_seconds": duration_seconds,
            "response_chain": _header_blocks_json(blocks),
            "response_headers": _header_fields_json(final_block),
            "set_cookies": json_value(_header_values(final_block, "Set-Cookie")),
            "content_type": ctype,
            "file": file,
            "curl_exit_code": int(proc.returncode or 0),
            "curl_error": stderr.strip(),
            "error": (
                _curl_failure_diagnostic(
                    int(proc.returncode or 0),
                    stderr.strip(),
                    metadata,
                )
                or _http_status_diagnostic(status)
            ),
            "redirect_follow_blocked_sensitive": bool(
                follow_redirects
                and sensitive_redirect_state
                and not forward_sensitive_headers_on_redirect
            ),
            **_preview(data, final_block, metadata, preview_bytes),
        }
    finally:
        header_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
