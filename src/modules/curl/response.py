from __future__ import annotations

from email.message import Message
from pathlib import Path
from urllib.parse import urlsplit

from common.models import JsonObject, JsonValue, json_object, json_value

from .errors import CurlError
from .models import BodyPreview, CurlDiagnostic, HeaderBlock, HeaderField

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
_DEFAULT_PREVIEW_BYTES = 4096

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
