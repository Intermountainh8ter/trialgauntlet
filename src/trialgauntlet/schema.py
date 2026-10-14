"""A deliberately small JSON-schema subset validator for tool arguments.

Supported keywords: type (string, integer, number, boolean, array, object), enum, required,
properties, additionalProperties (false), items, minimum, maximum, minLength.
"""

from __future__ import annotations

from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _type_ok(value: Any, type_name: str) -> bool:
    if type_name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[type_name])


def validate_args(schema: dict[str, Any], value: Any, path: str = "arguments") -> list[str]:
    """Return a list of human-readable problems (empty when ``value`` conforms)."""
    problems: list[str] = []
    type_name = schema.get("type")
    if type_name is not None and not _type_ok(value, type_name):
        return [f"{path}: expected {type_name}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        problems.append(f"{path}: must be at least {schema['minLength']} characters")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: {value} is above the maximum {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"{path}: missing required argument '{name}'")
        for name, item in value.items():
            if name in props:
                problems.extend(validate_args(props[name], item, f"{path}.{name}"))
            elif schema.get("additionalProperties") is False:
                problems.append(f"{path}: unexpected argument '{name}'")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            problems.extend(validate_args(schema["items"], item, f"{path}[{i}]"))
    return problems


def object_schema(properties: dict[str, dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    """Convenience constructor for the strict object schemas used by every built-in tool."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(required if required is not None else properties),
        "additionalProperties": False,
    }
