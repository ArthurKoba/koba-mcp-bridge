from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from common.models import JsonObject, JsonValue, json_loads, json_object, json_value
from modules.files.file_store import FileStore, upload_max_bytes

from .errors import CurlError
from .request import (
    _body_source,
    _cookie_header,
    _has_sensitive_redirect_state,
    _merged_headers,
    _redacted_request_headers,
    _validate_method,
    _validate_url,
    _with_query,
)

_MAX_REDIRECTS = 20

@lru_cache(maxsize=1)
def _system_curl_binary() -> str:
    found = shutil.which("curl")
    if not found:
        raise CurlError("curl executable is not installed")
    return found

def _curl_binary() -> str:
    configured = os.getenv("CURL_BINARY", "").strip()
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise CurlError("CURL_BINARY does not point to a file")
        return str(path)
    return _system_curl_binary()

def _metadata_from_stdout(stdout: str) -> JsonObject:
    text = stdout.strip()
    if not text:
        return {}
    try:
        value = json_loads(text, context="curl --write-out")
    except ValueError:
        return {"raw_write_out": text}
    if isinstance(value, dict):
        return json_object(value, context="curl --write-out")
    return {"write_out": value}

def _build_curl_command(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    cookies: dict[str, str] | None,
    body_path: Path | None,
    follow_redirects: bool,
    max_redirects: int,
    timeout_seconds: float,
    connect_timeout_seconds: float,
    verify_tls: bool,
    proxy_url: str,
    header_path: Path,
    output_path: Path,
    max_response_bytes: int,
) -> list[str]:
    if max_redirects < 0 or max_redirects > _MAX_REDIRECTS:
        raise CurlError(f"max_redirects must be between 0 and {_MAX_REDIRECTS}")
    if timeout_seconds <= 0 or timeout_seconds > 3600:
        raise CurlError("timeout_seconds must be greater than 0 and at most 3600")
    if connect_timeout_seconds <= 0 or connect_timeout_seconds > 300:
        raise CurlError(
            "connect_timeout_seconds must be greater than 0 and at most 300"
        )
    if max_response_bytes <= 0 or max_response_bytes > upload_max_bytes():
        raise CurlError(
            f"max_response_bytes must be between 1 and {upload_max_bytes()}"
        )

    args = [
        _curl_binary(),
        "--silent",
        "--show-error",
        "--compressed",
        "--request",
        method,
        "--url",
        url,
        "--connect-timeout",
        str(connect_timeout_seconds),
        "--max-time",
        str(timeout_seconds),
        "--max-redirs",
        str(max_redirects),
        "--dump-header",
        str(header_path),
        "--output",
        str(output_path),
        "--max-filesize",
        str(max_response_bytes),
        "--write-out",
        "%{json}",
    ]
    if follow_redirects:
        args.append("--location")
    if not verify_tls:
        args.append("--insecure")
    if proxy_url.strip():
        proxy = _validate_url(proxy_url)
        args.extend(["--proxy", proxy])

    for name, value in headers.items():
        args.extend(["--header", f"{name}: {value}"])
    cookie = _cookie_header(cookies)
    if cookie:
        args.extend(["--cookie", cookie])
    if body_path is not None:
        args.extend(["--data-binary", f"@{body_path}"])
    return args

def _execute_curl(
    *,
    method: str,
    url: str,
    query: JsonObject | None,
    headers: dict[str, str] | None,
    cookies: dict[str, str] | None,
    body_text: str | None,
    body_json: JsonObject | list[JsonValue] | None,
    body_form: JsonObject | None,
    body_base64: str | None,
    body_file_id: str | None,
    body_content_type: str,
    preset: str,
    follow_redirects: bool,
    max_redirects: int,
    timeout_seconds: float,
    connect_timeout_seconds: float,
    verify_tls: bool,
    proxy_url: str,
    max_response_bytes: int,
    forward_sensitive_headers_on_redirect: bool,
) -> tuple[JsonObject, Path, Path]:
    store = FileStore()
    store.ensure()
    clean_method = _validate_method(method)
    final_request_url = _with_query(_validate_url(url), query)
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

    fd_headers, raw_headers = tempfile.mkstemp(prefix="curl-headers-", dir=store.tmp)
    os.close(fd_headers)
    header_path = Path(raw_headers)
    fd_output, raw_output = tempfile.mkstemp(prefix="curl-output-", dir=store.tmp)
    os.close(fd_output)
    output_path = Path(raw_output)

    sensitive_redirect_state = _has_sensitive_redirect_state(merged, cookies)
    effective_follow_redirects = follow_redirects and (
        forward_sensitive_headers_on_redirect or not sensitive_redirect_state
    )

    command = _build_curl_command(
        method=clean_method,
        url=final_request_url,
        headers=merged,
        cookies=cookies,
        body_path=body_path,
        follow_redirects=effective_follow_redirects,
        max_redirects=max_redirects if effective_follow_redirects else 0,
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        verify_tls=verify_tls,
        proxy_url=proxy_url,
        header_path=header_path,
        output_path=output_path,
        max_response_bytes=max_response_bytes,
    )

    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(timeout_seconds + 5, connect_timeout_seconds + 5),
        )
    except subprocess.TimeoutExpired as exc:
        header_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        raise CurlError("curl process exceeded its execution timeout") from exc
    finally:
        if temporary_body is not None:
            temporary_body.unlink(missing_ok=True)

    metadata = _metadata_from_stdout(proc.stdout)
    metadata["curl_exit_code"] = proc.returncode
    metadata["curl_error"] = proc.stderr.strip()
    metadata["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    metadata["request_method"] = clean_method
    metadata["request_url"] = final_request_url
    metadata["request_headers"] = json_value(
        _redacted_request_headers(merged),
        context="curl request headers",
    )
    metadata["preset"] = preset
    metadata["redirect_follow_requested"] = follow_redirects
    metadata["redirect_follow_blocked_sensitive"] = bool(
        follow_redirects and sensitive_redirect_state and not forward_sensitive_headers_on_redirect
    )
    return metadata, header_path, output_path
