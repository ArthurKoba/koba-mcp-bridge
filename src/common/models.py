from __future__ import annotations

from collections.abc import Callable
from typing import ParamSpec, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    TypeAdapter,
    ValidationError,
    validate_call,
)

P = ParamSpec("P")
R = TypeVar("R")

type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )


class ProviderModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        strict=True,
    )


_JSON_VALUE = TypeAdapter(JsonValue)
_JSON_OBJECT = TypeAdapter(JsonObject)
_JSON_ARRAY = TypeAdapter(JsonArray)
_STRICT_CALL_CONFIG = ConfigDict(strict=True, arbitrary_types_allowed=True)


def validated_call(function: Callable[P, R]) -> Callable[P, R]:
    wrapped = validate_call(
        config=_STRICT_CALL_CONFIG,
        validate_return=True,
    )(function)
    return cast(Callable[P, R], wrapped)


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


def model_json(model: BaseModel) -> JsonObject:
    return json_object(model.model_dump(mode="json"))
