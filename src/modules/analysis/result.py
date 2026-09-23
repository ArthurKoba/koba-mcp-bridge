from __future__ import annotations

from typing import cast

from common.models import JsonValue, json_loads, json_value


def decode_result(data: object) -> JsonValue:
    """Recursively unwrap backend result envelopes and JSON strings."""
    value: object = data
    for _ in range(8):
        if isinstance(value, dict) and "result" in value:
            nested = value["result"]
            if nested is value:
                return json_value(value, context="analysis backend result")
            value = nested
            continue
        if isinstance(value, str):
            try:
                decoded = json_loads(value, context="analysis backend result")
            except ValueError:
                return value
            if decoded == value:
                return value
            value = decoded
            continue
        return json_value(value, context="analysis backend result")
    return json_value(value, context="analysis backend result")


def decode_call_result(result: object) -> JsonValue | None:
    """Decode FastMCP results across structured and legacy content forms."""
    candidates: list[object | None] = [
        cast(object | None, getattr(result, "structured_content", None)),
        cast(object | None, getattr(result, "data", None)),
    ]
    content = cast(object | None, getattr(result, "content", None))
    if isinstance(content, list):
        for block in content:
            text = cast(object | None, getattr(block, "text", None))
            if isinstance(text, str):
                candidates.append(text)

    for candidate in candidates:
        if candidate is None:
            continue
        decoded = decode_result(candidate)
        if decoded is not None:
            return decoded
    return None
