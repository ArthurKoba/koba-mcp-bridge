from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, validate_call
from pydantic import JsonValue as JsonValue

type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]
type JsonContainer = JsonObject | JsonArray


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )

    def to_json(self) -> JsonObject:
        return json_object(self.model_dump(mode="json"), context=type(self).__name__)


class ProviderModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        strict=True,
    )

    def to_json(self) -> JsonObject:
        return json_object(self.model_dump(mode="json"), context=type(self).__name__)


_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_JSON_ARRAY: TypeAdapter[JsonArray] = TypeAdapter(JsonArray)
_JSON_OBJECT_LIST: TypeAdapter[list[JsonObject]] = TypeAdapter(list[JsonObject])
_STRICT_CALL_CONFIG = ConfigDict(strict=True, arbitrary_types_allowed=True)


def validated_call[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    return validate_call(
        config=_STRICT_CALL_CONFIG,
        validate_return=True,
    )(function)


def json_loads(data: str | bytes, *, context: str = "value") -> JsonValue:
    try:
        return _JSON_VALUE.validate_json(data)
    except ValidationError as exc:
        raise ValueError(f"{context} is not valid JSON") from exc


def json_value(value: object, *, context: str = "value") -> JsonValue:
    try:
        return _JSON_VALUE.validate_python(value, strict=True)
    except ValidationError as exc:
        raise ValueError(f"{context} is not valid JSON-compatible data") from exc


def json_object(value: object, *, context: str = "value") -> JsonObject:
    try:
        return _JSON_OBJECT.validate_python(value, strict=True)
    except ValidationError as exc:
        raise ValueError(f"{context} must be a JSON object") from exc


def json_array(value: object, *, context: str = "value") -> JsonArray:
    try:
        return _JSON_ARRAY.validate_python(value, strict=True)
    except ValidationError as exc:
        raise ValueError(f"{context} must be a JSON array") from exc


def json_container(value: object, *, context: str = "value") -> JsonContainer:
    normalized = json_value(value, context=context)
    if isinstance(normalized, (dict, list)):
        return normalized
    raise ValueError(f"{context} must be a JSON object or array")


def json_str(value: JsonValue | object, *, default: str = "", field: str = "value") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return str(value)
    raise ValueError(f"{field} must be a JSON scalar")


def json_int(value: JsonValue | object, *, default: int = 0, field: str = "value") -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{field} must be an integer")
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be an integer") from exc
    raise ValueError(f"{field} must be an integer")


def json_float(
    value: JsonValue | object,
    *,
    default: float = 0.0,
    field: str = "value",
) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a number") from exc
    raise ValueError(f"{field} must be a number")


def json_bool(
    value: JsonValue | object,
    *,
    default: bool = False,
    field: str = "value",
) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"{field} must be a boolean")


def json_member_object(
    payload: JsonObject,
    key: str,
    *,
    required: bool = False,
) -> JsonObject:
    value = payload.get(key)
    if value is None and not required:
        return {}
    try:
        return json_object(value, context=key)
    except ValueError as exc:
        if required:
            raise ValueError(f"{key} must be a JSON object") from exc
        return {}


def json_member_array(
    payload: JsonObject,
    key: str,
    *,
    required: bool = False,
) -> JsonArray:
    value = payload.get(key)
    if value is None and not required:
        return []
    try:
        return json_array(value, context=key)
    except ValueError as exc:
        if required:
            raise ValueError(f"{key} must be a JSON array") from exc
        return []


def json_object_list(value: JsonValue | object, *, context: str = "value") -> list[JsonObject]:
    try:
        return _JSON_OBJECT_LIST.validate_python(value, strict=True)
    except ValidationError as exc:
        raise ValueError(f"{context} must be a list of JSON objects") from exc
