from __future__ import annotations

from collections.abc import Mapping


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]
type JsonMapping = Mapping[str, JsonValue]
