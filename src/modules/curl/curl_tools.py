from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from email.message import Message
from functools import lru_cache
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from common.models import JsonObject, JsonValue, json_loads, json_object, json_value
from modules.files.file_store import FileStore, upload_max_bytes
from modules.files.models import FileInfo

from .models import (
    BodyPreview,
    CurlDiagnostic,
    CurlPreset,
    CurlPresetDefinition,
    CurlPresetsResponse,
    HeaderBlock,
    HeaderField,
)


class CurlError(ValueError):
    pass


_METHOD_RE = re.compile(r"^[A-Za-z!#$%&'*+.^_|~-]+$")
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_~|0-9A-Za-z]+$")
_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_~|0-9A-Za-z]+$")
_TEXTUAL_TYPES = (
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
    "application/x-javascript",
    "application/x-www-form-urlencoded",
    "image/svg+xml",
)
_SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization"}
_DEFAULT_PREVIEW_BYTES = 4096
_DEFAULT_REQUEST_MAX_BYTES = 2 * 1024 * 1024
_MAX_REQUEST_MAX_BYTES = 16 * 1024 * 1024
_DEFAULT_DOWNLOAD_MAX_BYTES = 1024 * 1024 * 1024
_MAX_DURATION_SECONDS = 300
_MAX_REDIRECTS = 20
DEFAULT_CURL_PRESET = "chrome-desktop"


_RAW_PRESETS: dict[str, JsonObject] = {
    "curl": {
        "description": "Native curl defaults plus automatic compressed-response decoding.",
        "headers": {"Accept": "*/*"},
    },
    "chrome-desktop": {
        "description": (
            "Browser-like desktop Chrome HTTP headers. This is not a JavaScript engine "
            "and does not reproduce Chrome TLS/HTTP2 fingerprints."
        ),
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/153.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-CH-UA": (
                '"Chromium";v="153", "Not_A Brand";v="99", '
                '"Google Chrome";v="153"'
            ),
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Upgrade-Insecure-Requests": "1",
        },
    },
    "chrome-mobile": {
        "description": (
            "Browser-like Android Chrome HTTP headers. This is not a JavaScript engine "
            "and does not reproduce Chrome TLS/HTTP2 fingerprints."
        ),
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 15; Pixel 9) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/153.0.0.0 Mobile Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-CH-UA": (
                '"Chromium";v="153", "Not_A Brand";v="99", '
                '"Google Chrome";v="153"'
            ),
            "Sec-CH-UA-Mobile": "?1",
            "Sec-CH-UA-Platform": '"Android"',
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Upgrade-Insecure-Requests": "1",
        },
    },
    "json-api": {
        "description": "JSON API defaults.",
        "headers": {
            "User-Agent": "MCP-Bridge-Curl/1.0",
            "Accept": "application/json",
        },
    },
    "none": {
        "description": "No preset headers; only caller-provided headers are sent.",
        "headers": {},
    },
}
_PRESETS = {
    name: CurlPresetDefinition.model_validate(payload)
    for name, payload in _RAW_PRESETS.items()
}



def curl_presets_impl() -> JsonObject:
    return CurlPresetsResponse(
        default_preset=DEFAULT_CURL_PRESET,
        presets=[
            CurlPreset(
                name=name,
                description=data.description,
                headers=dict(data.headers),
            )
            for name, data in _PRESETS.items()
        ],
    ).to_json()


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

def _validate_method(method: str) -> str:
    value = method.strip().upper()
    if not value or not _METHOD_RE.fullmatch(value):
        raise CurlError("method contains invalid HTTP token characters")
    return value


def _validate_url(url: str) -> str:
    value = url.strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise CurlError("url is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise CurlError("url scheme must be http or https")
    if not parsed.hostname:
        raise CurlError("url must include a hostname")
    return value


def _query_pairs(query: JsonObject | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, raw in (query or {}).items():
        name = str(key)
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            if value is None:
                pairs.append((name, ""))
            elif isinstance(value, bool):
                pairs.append((name, "true" if value else "false"))
            else:
                pairs.append((name, str(value)))
    return pairs


def _with_query(url: str, query: JsonObject | None) -> str:
    if not query:
        return url
    parsed = urlsplit(url)
    existing = parse_qsl(parsed.query, keep_blank_values=True)
    merged = [*existing, *_query_pairs(query)]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(merged, doseq=True),
            parsed.fragment,
        )
    )


def _validate_header(name: str, value: str) -> tuple[str, str]:
    clean_name = name.strip()
    if not _HEADER_NAME_RE.fullmatch(clean_name):
        raise CurlError(f"invalid HTTP header name: {name!r}")
    clean_value = str(value)
    if "\r" in clean_value or "\n" in clean_value or "\x00" in clean_value:
        raise CurlError(f"header {clean_name!r} contains control characters")
    return clean_name, clean_value


def _merged_headers(preset: str, headers: dict[str, str] | None) -> dict[str, str]:
    preset_name = preset.strip().casefold() or DEFAULT_CURL_PRESET
    if preset_name not in _PRESETS:
        raise CurlError("preset must be one of: " + ", ".join(sorted(_PRESETS)))
    result: dict[str, tuple[str, str]] = {}
    for name, value in _PRESETS[preset_name].headers.items():
        clean_name, clean_value = _validate_header(name, value)
        result[clean_name.casefold()] = (clean_name, clean_value)
    for name, value in (headers or {}).items():
        clean_name, clean_value = _validate_header(str(name), str(value))
        result[clean_name.casefold()] = (clean_name, clean_value)
    return dict(result.values())


def _cookie_header(cookies: dict[str, str] | None) -> str:
    parts: list[str] = []
    for raw_name, raw_value in (cookies or {}).items():
        name = str(raw_name).strip()
        if not _COOKIE_NAME_RE.fullmatch(name):
            raise CurlError(f"invalid cookie name: {raw_name!r}")
        value = str(raw_value)
        if "\r" in value or "\n" in value or "\x00" in value:
            raise CurlError(f"cookie {name!r} contains control characters")
        cookie = SimpleCookie()
        cookie[name] = value
        parts.append(cookie[name].OutputString())
    return "; ".join(parts)


def _has_header(headers: dict[str, str], name: str) -> bool:
    needle = name.casefold()
    return any(key.casefold() == needle for key in headers)


def _has_sensitive_redirect_state(
    headers: dict[str, str],
    cookies: dict[str, str] | None,
) -> bool:
    return bool(cookies) or any(
        name.casefold() in _SENSITIVE_HEADERS for name in headers
    )


def _body_source(
    *,
    body_text: str | None,
    body_json: JsonObject | list[JsonValue] | None,
    body_form: JsonObject | None,
    body_base64: str | None,
    body_file_id: str | None,
    body_content_type: str,
    headers: dict[str, str],
    store: FileStore,
) -> tuple[Path | None, Path | None]:
    supplied = sum(
        value is not None and value != ""
        for value in (
            body_text,
            body_json,
            body_form,
            body_base64,
            body_file_id,
        )
    )
    if supplied > 1:
        raise CurlError(
            "only one body source may be used: body_text, body_json, body_form, "
            "body_base64, or body_file_id"
        )

    content_type = body_content_type.strip()
    if body_file_id:
        file = FileInfo.model_validate(store.info(body_file_id))
        if content_type and not _has_header(headers, "Content-Type"):
            headers["Content-Type"] = content_type
        elif not _has_header(headers, "Content-Type"):
            mime = file.mime_type.strip()
            if mime:
                headers["Content-Type"] = mime
        return store.path_for(body_file_id), None

    data: bytes | None = None
    if body_json is not None:
        data = json.dumps(
            body_json,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if not _has_header(headers, "Content-Type"):
            headers["Content-Type"] = content_type or "application/json"
    elif body_form is not None:
        data = urlencode(_query_pairs(body_form), doseq=True).encode("utf-8")
        if not _has_header(headers, "Content-Type"):
            headers["Content-Type"] = content_type or "application/x-www-form-urlencoded"
    elif body_base64:
        try:
            data = base64.b64decode(body_base64, validate=True)
        except Exception as exc:
            raise CurlError("body_base64 is not valid base64") from exc
        if content_type and not _has_header(headers, "Content-Type"):
            headers["Content-Type"] = content_type
    elif body_text is not None:
        data = body_text.encode("utf-8")
        if content_type and not _has_header(headers, "Content-Type"):
            headers["Content-Type"] = content_type

    if data is None:
        return None, None
    if len(data) > upload_max_bytes():
        raise CurlError("request body exceeds FILE_UPLOAD_MAX_BYTES")

    store.ensure()
    fd, raw = tempfile.mkstemp(prefix="curl-body-", dir=store.tmp)
    path = Path(raw)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return path, path


def _redacted_request_headers(headers: dict[str, str]) -> list[dict[str, str]]:
    result = []
    for name, value in headers.items():
        shown = "<redacted>" if name.casefold() in _SENSITIVE_HEADERS else value
        result.append({"name": name, "value": shown})
    return result


def _parse_header_blocks(path: Path) -> list[HeaderBlock]:
    if not path.is_file():
        return []
    raw = path.read_bytes().decode("iso-8859-1", errors="replace")
    lines = raw.replace("\r\n", "\n").split("\n")
    blocks: list[HeaderBlock] = []
    current: HeaderBlock | None = None
    for line in lines:
        if line.startswith("HTTP/"):
            if current is not None:
                blocks.append(current)
            parts = line.split(" ", 2)
            status = 0
            if len(parts) >= 2:
                try:
                    status = int(parts[1])
                except ValueError:
                    status = 0
            current = HeaderBlock(status_line=line, status=status, headers=[])
            continue
        if current is None:
            continue
        if not line:
            blocks.append(current)
            current = None
            continue
        if line[:1] in {" ", "\t"} and current.headers:
            current.headers[-1].value += " " + line.strip()
            continue
        if ":" in line:
            name, value = line.split(":", 1)
            current.headers.append(
                HeaderField(name=name.strip(), value=value.lstrip())
            )
    if current is not None:
        blocks.append(current)
    return blocks


def _header_values(block: HeaderBlock | None, name: str) -> list[str]:
    if not block:
        return []
    needle = name.casefold()
    return [
        item.value
        for item in block.headers
        if item.name.casefold() == needle
    ]


def _content_type(block: HeaderBlock | None, metadata: JsonObject) -> str:
    values = _header_values(block, "Content-Type")
    if values:
        return values[-1].split(";", 1)[0].strip().casefold()
    return str(metadata.get("content_type") or "").split(";", 1)[0].strip().casefold()


def _charset(block: HeaderBlock | None) -> str:
    values = _header_values(block, "Content-Type")
    if not values:
        return "utf-8"
    message = Message()
    message["content-type"] = values[-1]
    return message.get_content_charset() or "utf-8"


def _looks_textual(content_type: str, data: bytes) -> bool:
    if content_type.startswith("text/") or content_type in _TEXTUAL_TYPES:
        return True
    if content_type.endswith(("+json", "+xml")):
        return True
    if not data:
        return True
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _preview(
    data: bytes,
    block: HeaderBlock | None,
    metadata: JsonObject,
    preview_bytes: int = _DEFAULT_PREVIEW_BYTES,
) -> JsonObject:
    preview_size = max(0, min(int(preview_bytes), 64 * 1024))
    sample = data[:preview_size]
    ctype = _content_type(block, metadata)
    if _looks_textual(ctype, sample):
        charset = _charset(block)
        try:
            text = sample.decode(charset, errors="replace")
        except LookupError:
            charset = "utf-8"
            text = sample.decode("utf-8", errors="replace")
        return BodyPreview(
            body_is_text=True,
            body_encoding=charset,
            body_preview_text=text,
        ).to_json()
    return BodyPreview(
        body_is_text=False,
        body_preview_hex=sample[:512].hex(),
    ).to_json()


def _safe_file_name(name: str) -> str:
    value = Path(name.replace("\\", "/")).name.strip()
    value = "".join(ch for ch in value if ord(ch) >= 32 and ch not in {"/", "\\"})
    if not value:
        return "download.bin"
    return value[:240]


def _response_filename(
    explicit: str,
    final_url: str,
    block: HeaderBlock | None,
    fallback: str,
) -> str:
    if explicit.strip():
        return _safe_file_name(explicit)
    values = _header_values(block, "Content-Disposition")
    if values:
        message = Message()
        message["content-disposition"] = values[-1]
        filename = message.get_filename()
        if filename:
            return _safe_file_name(filename)
    path_name = Path(urlsplit(final_url).path).name
    if path_name:
        return _safe_file_name(path_name)
    return fallback


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


def _json_int(value: JsonValue | None, *, default: int = 0, field: str = "value") -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise CurlError(f"{field} is not an integer") from exc
    raise CurlError(f"{field} is not a scalar integer value")


def _header_blocks_json(blocks: list[HeaderBlock]) -> JsonValue:
    return json_value(
        [block.to_json() for block in blocks],
        context="curl response headers",
    )


def _header_fields_json(block: HeaderBlock | None) -> JsonValue:
    return json_value(
        [field.to_json() for field in block.headers] if block else [],
        context="curl response header fields",
    )


def _curl_failure_diagnostic(
    exit_code: int,
    error: str,
    metadata: JsonObject | None = None,
) -> JsonObject | None:
    code = int(exit_code)
    if code == 0:
        return None

    categories = {
        5: (
            "proxy_dns",
            "curl could not resolve the configured proxy hostname",
        ),
        6: (
            "dns",
            "curl could not resolve the target hostname",
        ),
        7: (
            "connect",
            "curl could not establish a TCP connection to the target",
        ),
        28: (
            "timeout",
            "the request exceeded the configured connect or total timeout",
        ),
        35: (
            "tls_handshake",
            "the TLS handshake failed; check protocol/cipher compatibility",
        ),
        47: (
            "redirect_loop",
            "the request exceeded the configured redirect limit",
        ),
        51: (
            "tls_identity",
            "the TLS certificate hostname/identity did not match",
        ),
        52: (
            "empty_reply",
            "the peer closed the connection without returning an HTTP response",
        ),
        55: (
            "send",
            "curl failed while sending request data",
        ),
        56: (
            "receive",
            "curl failed while receiving response data",
        ),
        60: (
            "tls_certificate",
            "TLS certificate verification failed; check CA trust and certificate validity",
        ),
        63: (
            "max_bytes",
            "the response exceeded the configured maximum response size",
        ),
    }
    error_type, hint = categories.get(
        code,
        ("curl", "curl failed before completing the HTTP request"),
    )
    clean_error = error.strip()
    meta = metadata or {}
    if code == 28:
        connect = meta.get("time_connect")
        total = meta.get("time_total")
        if connect is not None or total is not None:
            hint += f"; time_connect={connect!s}, time_total={total!s}"
    return CurlDiagnostic(
        error_type=error_type,
        error_hint=hint,
        error_detail=clean_error[:2048] if clean_error else None,
    ).to_json()


def _http_status_diagnostic(status: int) -> JsonObject | None:
    code = int(status)
    if code < 400:
        return None
    if code == 401:
        return CurlDiagnostic(
            error_type="http_authentication",
            error_hint="the server rejected authentication credentials (HTTP 401)",
        ).to_json()
    if code == 403:
        return CurlDiagnostic(
            error_type="http_forbidden",
            error_hint="the server understood the request but denied permission (HTTP 403)",
        ).to_json()
    if code == 407:
        return CurlDiagnostic(
            error_type="proxy_authentication",
            error_hint="the configured proxy requires authentication (HTTP 407)",
        ).to_json()
    if code == 429:
        return CurlDiagnostic(
            error_type="http_rate_limit",
            error_hint="the server rate-limited the request (HTTP 429)",
        ).to_json()
    if 500 <= code <= 599:
        return CurlDiagnostic(
            error_type="http_server",
            error_hint=f"the remote server returned HTTP {code}",
        ).to_json()
    return CurlDiagnostic(
        error_type="http_client",
        error_hint=f"the remote server returned HTTP {code}",
    ).to_json()


def _http_result(
    *,
    metadata: JsonObject,
    header_path: Path,
    output_path: Path,
    response_max_bytes: int,
    preview_bytes: int,
) -> JsonObject:
    blocks = _parse_header_blocks(header_path)
    final_block = blocks[-1] if blocks else None
    status = _json_int(
        metadata.get("http_code"),
        default=final_block.status if final_block else 0,
        field="http_code",
    )
    final_url = str(metadata.get("url_effective") or metadata.get("request_url") or "")
    size = output_path.stat().st_size if output_path.is_file() else 0
    exit_code = _json_int(metadata.get("curl_exit_code"), field="curl_exit_code")
    truncated = bool(exit_code == 63 or size >= response_max_bytes)
    data = output_path.read_bytes() if output_path.is_file() else b""
    result: JsonObject = {
        "status": status,
        "ok": 200 <= status < 400 and exit_code == 0,
        "final_url": final_url,
        "redirect_count": _json_int(
            metadata.get("num_redirects"),
            default=max(0, len(blocks) - 1),
            field="num_redirects",
        ),
        "response_chain": _header_blocks_json(blocks),
        "response_headers": _header_fields_json(final_block),
        "set_cookies": json_value(_header_values(final_block, "Set-Cookie")),
        "content_type": _content_type(final_block, metadata),
        "body_size_bytes": size,
        "body_truncated": truncated,
        "curl_exit_code": exit_code,
        "curl_error": str(metadata.get("curl_error") or ""),
        "redirect_follow_blocked_sensitive": bool(
            metadata.get("redirect_follow_blocked_sensitive")
        ),
        "timings": {
            key: metadata.get(key)
            for key in (
                "time_namelookup",
                "time_connect",
                "time_appconnect",
                "time_pretransfer",
                "time_starttransfer",
                "time_total",
                "elapsed_ms",
            )
            if metadata.get(key) is not None
        },
        "network": {
            key: metadata.get(key)
            for key in (
                "remote_ip",
                "remote_port",
                "local_ip",
                "local_port",
                "http_version",
                "ssl_verify_result",
            )
            if metadata.get(key) not in (None, "")
        },
        "request": {
            "method": metadata.get("request_method"),
            "url": metadata.get("request_url"),
            "preset": metadata.get("preset"),
            "headers": metadata.get("request_headers", []),
        },
    }
    diagnostic = _curl_failure_diagnostic(
        exit_code,
        str(metadata.get("curl_error") or ""),
        metadata,
    )
    if diagnostic is None:
        diagnostic = _http_status_diagnostic(status)
    if diagnostic is not None:
        result["error"] = diagnostic
    preview = _preview(data, final_block, metadata, preview_bytes)
    result.update(preview)
    if preview.get("body_is_text") is True and not truncated:
        charset = str(preview.get("body_encoding") or "utf-8")
        try:
            result["body_text"] = data.decode(charset, errors="replace")
        except LookupError:
            result["body_encoding"] = "utf-8"
            result["body_text"] = data.decode("utf-8", errors="replace")
    return json_object(result, context="curl request response")


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
