from __future__ import annotations

import json
from typing import cast

from .types import JsonArray, JsonObject, JsonValue


class JsonTypeError(TypeError):
    pass


def normalize_json(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    if isinstance(value, dict):
        result: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise JsonTypeError("JSON object keys must be strings")
            result[key] = normalize_json(item)
        return result
    raise JsonTypeError(f"unsupported JSON value type: {type(value).__name__}")


def json_loads(text: str) -> JsonValue:
    raw = cast(object, json.loads(text))
    return normalize_json(raw)


def json_object(value: object, *, context: str = "value") -> JsonObject:
    normalized = normalize_json(value)
    if not isinstance(normalized, dict):
        raise JsonTypeError(f"{context} must be a JSON object")
    return normalized


def json_array(value: object, *, context: str = "value") -> JsonArray:
    normalized = normalize_json(value)
    if not isinstance(normalized, list):
        raise JsonTypeError(f"{context} must be a JSON array")
    return normalized
