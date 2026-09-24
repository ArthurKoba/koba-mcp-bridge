from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence

MAX_PAYLOAD_CHARS = 65_536
REDACTED = "<redacted>"

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set_cookie",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "client_secret",
    "credential",
    "private_key",
    "private_key_pem",
    "api_key",
    "download_url",
}

_TEXT_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(\bauthorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
    ),
    re.compile(r"(?i)(\b(?:private-token|job-token)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(\bBearer\s+)[^\s,;]+"),
    re.compile(
        r"(?i)(\b(?:access_token|refresh_token|token|password|secret|client_secret|api_key)"
        r"\s*[:=]\s*)[^\s&;,]+"
    ),
    re.compile(
        r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
        re.IGNORECASE | re.DOTALL,
    ),
)

_SENSITIVE_SUFFIXES = (
    "_token",
    "_password",
    "_secret",
    "_credential",
    "_private_key",
    "_api_key",
)


def _key_is_sensitive(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _structured(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except Exception:
            pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            return dataclasses.asdict(value)
        except Exception:
            pass
    return value


def redact_payload(value: object) -> object:
    value = _structured(value)
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _key_is_sensitive(key) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def render_payload(value: object) -> str:
    sanitized = redact_payload(value)
    try:
        rendered = json.dumps(sanitized, ensure_ascii=False, default=str)
    except Exception:
        rendered = repr(sanitized)
    return rendered[:MAX_PAYLOAD_CHARS]


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _TEXT_SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)
    return redacted


def render_error(value: object) -> str:
    return redact_text(str(value))[:MAX_PAYLOAD_CHARS]
