from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Literal, Protocol, cast

from pydantic import AliasChoices, ConfigDict, Field, create_model
from pydantic.fields import FieldInfo

from common.models import JsonObject, JsonValue, StrictModel, json_object, json_value

Surface = Literal["ghidra", "analysis"]


class ToolArgumentsBase(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class ToolAlias(StrictModel):
    ghidra_name: str
    analysis_name: str
    argument_aliases: dict[str, str]


class _DynamicModelFactory(Protocol):
    def __call__(
        self,
        model_name: str,
        /,
        *,
        __base__: type[ToolArgumentsBase],
        **field_definitions: tuple[object, FieldInfo],
    ) -> type[ToolArgumentsBase]: ...


_ARGUMENT_ALIASES: dict[str, str] = {
    "function": "action",
    "function_name": "action_name",
    "function_address": "action_address",
    "function_names": "action_names",
    "start_function": "start_action",
    "end_function": "end_action",
    "source_function": "source_action",
    "target_function": "target_action",
    "caller": "inbound_action",
    "callers": "inbound_actions",
    "callee": "outbound_action",
    "callees": "outbound_actions",
    "include_callers": "include_inbound_actions",
    "include_callees": "include_outbound_actions",
    "include_disasm": "include_low_level_view",
    "decompiler_comments": "behavior_annotations",
    "disassembly_comments": "low_level_annotations",
}

_TOOL_PHRASES: tuple[tuple[str, str], ...] = (
    ("analyze_call_graph", "analyze_link_map"),
    ("get_function_callers", "get_inbound_actions"),
    ("get_function_callees", "get_outbound_actions"),
    ("decompile_function", "inspect_action_behavior"),
    ("disassemble_function", "inspect_low_level_action"),
    ("rename_function", "name_action"),
    ("function_callers", "inbound_actions"),
    ("function_callees", "outbound_actions"),
    ("call_graph", "link_map"),
    ("cross_references", "links"),
    ("cross_reference", "link"),
)

_TOOL_TOKENS: dict[str, str] = {
    "functions": "actions",
    "function": "action",
    "callers": "inbound_actions",
    "caller": "inbound_action",
    "callees": "outbound_actions",
    "callee": "outbound_action",
    "xrefs": "links",
    "xref": "link",
}

_TEXT_TERMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\breverse engineering\b", re.IGNORECASE), "behavior analysis"),
    (re.compile(r"\breversing\b", re.IGNORECASE), "behavior recovery"),
    (re.compile(r"\bcall graph\b", re.IGNORECASE), "link map"),
    (re.compile(r"\bcross[- ]references?\b", re.IGNORECASE), "links"),
    (re.compile(r"\bxrefs?\b", re.IGNORECASE), "links"),
    (re.compile(r"\bdecompil(?:e|ation|er view)\b", re.IGNORECASE), "inspect behavior"),
    (re.compile(r"\bdisassembly\b", re.IGNORECASE), "low-level action view"),
    (re.compile(r"\bcallers\b", re.IGNORECASE), "inbound actions"),
    (re.compile(r"\bcaller\b", re.IGNORECASE), "inbound action"),
    (re.compile(r"\bcallees\b", re.IGNORECASE), "outbound actions"),
    (re.compile(r"\bcallee\b", re.IGNORECASE), "outbound action"),
    (re.compile(r"\bfunctions\b", re.IGNORECASE), "action nodes"),
    (re.compile(r"\bfunction\b", re.IGNORECASE), "action node"),
)


def analysis_argument_name(
    ghidra_name: str,
    property_schema: JsonObject | None = None,
) -> str:
    if property_schema is not None:
        schema_alias = property_schema.get("x-analysis-alias")
        if isinstance(schema_alias, str) and schema_alias.strip():
            return schema_alias.strip()
    return _ARGUMENT_ALIASES.get(ghidra_name, ghidra_name)


def analysis_tool_name(ghidra_name: str) -> str:
    value = ghidra_name
    for source, target in _TOOL_PHRASES:
        value = value.replace(source, target)
    parts = value.split("_")
    translated = [_TOOL_TOKENS.get(part, part) for part in parts]
    return "_".join(translated)


def analysis_text(text: str) -> str:
    value = text
    for pattern, replacement in _TEXT_TERMS:
        value = pattern.sub(replacement, value)
    return value


def tool_alias(ghidra_name: str, input_schema: JsonObject) -> ToolAlias:
    properties = _schema_properties(input_schema)
    aliases = {
        name: analysis_argument_name(name, property_schema)
        for name, property_schema in properties.items()
        if analysis_argument_name(name, property_schema) != name
    }
    return ToolAlias(
        ghidra_name=ghidra_name,
        analysis_name=analysis_tool_name(ghidra_name),
        argument_aliases=aliases,
    )


def analysis_schema(input_schema: JsonObject) -> JsonObject:
    schema = json.loads(json.dumps(input_schema))
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return json_object(schema, context="analysis tool schema")

    renamed: dict[str, JsonValue] = {}
    owners: dict[str, str] = {}
    for ghidra_name, raw_property in properties.items():
        canonical = str(ghidra_name)
        property_schema = json_object(raw_property, context="tool property schema")
        alias = analysis_argument_name(canonical, property_schema)
        owner = owners.get(alias)
        if owner is not None and owner != canonical:
            raise ValueError(
                f"analysis argument alias collision: {owner!r} and "
                f"{canonical!r} -> {alias!r}"
            )
        owners[alias] = canonical
        description = property_schema.get("description")
        if isinstance(description, str):
            property_schema["description"] = analysis_text(description)
        renamed[alias] = property_schema
    schema["properties"] = renamed

    required = schema.get("required")
    if isinstance(required, list):
        source_properties = _schema_properties(input_schema)
        schema["required"] = [
            analysis_argument_name(
                str(name),
                source_properties.get(str(name)),
            )
            for name in required
        ]
    return json_object(schema, context="analysis tool schema")


def normalize_arguments(input_schema: JsonObject, arguments: JsonObject) -> JsonObject:
    model = _argument_model(_schema_cache_key(input_schema))
    _reject_alias_conflicts(input_schema, arguments)
    validated = model.model_validate(arguments)
    return json_object(validated.model_dump(mode="json"), context="normalized tool arguments")


def arguments_for_surface(
    input_schema: JsonObject,
    arguments: JsonObject,
    surface: Surface,
) -> JsonObject:
    model = _argument_model(_schema_cache_key(input_schema))
    _reject_alias_conflicts(input_schema, arguments)
    validated = model.model_validate(arguments)
    return json_object(
        validated.model_dump(mode="json", by_alias=surface == "analysis"),
        context=f"{surface} tool arguments",
    )


def _schema_properties(input_schema: JsonObject) -> dict[str, JsonObject]:
    raw = input_schema.get("properties")
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): json_object(schema, context=f"tool property {name}")
        for name, schema in raw.items()
        if isinstance(schema, dict)
    }


def _schema_cache_key(input_schema: JsonObject) -> str:
    return json.dumps(input_schema, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=512)
def _argument_model(schema_key: str) -> type[ToolArgumentsBase]:
    schema = json_object(json.loads(schema_key), context="tool input schema")
    properties = _schema_properties(schema)
    required_raw = schema.get("required")
    required = {str(name) for name in required_raw} if isinstance(required_raw, list) else set()

    fields: dict[str, tuple[object, FieldInfo]] = {}
    for ghidra_name, property_schema in properties.items():
        field_type = _python_type(property_schema)
        default: object
        if ghidra_name in required and "default" not in property_schema:
            default = ...
        else:
            default = property_schema.get("default")
        analysis_name = analysis_argument_name(ghidra_name, property_schema)
        if analysis_name == ghidra_name:
            field = cast(FieldInfo, Field(default=default))
        else:
            field = cast(
                FieldInfo,
                Field(
                    default=default,
                    validation_alias=AliasChoices(ghidra_name, analysis_name),
                    serialization_alias=analysis_name,
                ),
            )
        fields[ghidra_name] = (field_type, field)

    model_factory = cast(_DynamicModelFactory, create_model)
    return model_factory(
        "ToolArguments",
        __base__=ToolArgumentsBase,
        **fields,
    )


def _python_type(property_schema: JsonObject) -> object:
    raw_type = property_schema.get("type")
    if isinstance(raw_type, list):
        non_null = [
            value
            for value in raw_type
            if isinstance(value, str) and value != "null"
        ]
        raw_type = non_null[0] if len(non_null) == 1 else None
    if not isinstance(raw_type, str):
        return JsonValue
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list[JsonValue],
        "object": JsonObject,
    }.get(raw_type, JsonValue)


def _reject_alias_conflicts(input_schema: JsonObject, arguments: JsonObject) -> None:
    for ghidra_name, property_schema in _schema_properties(input_schema).items():
        analysis_name = analysis_argument_name(ghidra_name, property_schema)
        if analysis_name == ghidra_name:
            continue
        if ghidra_name not in arguments or analysis_name not in arguments:
            continue
        canonical = json_value(arguments[ghidra_name])
        aliased = json_value(arguments[analysis_name])
        if canonical != aliased:
            raise ValueError(
                f"conflicting values for {ghidra_name!r} and alias {analysis_name!r}"
            )
