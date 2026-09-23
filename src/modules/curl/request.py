from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from common.models import JsonObject, JsonValue
from modules.files.file_store import FileStore, upload_max_bytes
from modules.files.models import FileInfo

from .errors import CurlError
from .presets import _PRESETS, DEFAULT_CURL_PRESET

_METHOD_RE = re.compile(r"^[A-Za-z!#$%&'*+.^_|~-]+$")
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_~|0-9A-Za-z]+$")
_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_~|0-9A-Za-z]+$")
_SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization"}

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
