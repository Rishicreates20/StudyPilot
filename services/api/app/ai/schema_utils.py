"""Turn a Pydantic model into the JSON Schema subset the model providers accept.

Gemini's structured output supports a documented subset of JSON Schema. Pydantic emits more
(``$defs`` references, titles, defaults, string patterns), so the schema we send is flattened and
reduced to the supported keywords. That only shapes what the model is *asked* to produce; every
answer is still validated against the real Pydantic model afterwards, which enforces everything
the reduced schema leaves out.
"""

from typing import Any, cast

# Documented as supported by Gemini structured output (checked 2026-10-11), minus `maxItems`:
# the live API answered a bare "400 Request contains an invalid argument" for the roadmap
# schema until `maxItems` was removed (bisected with the owner's key; every other keyword
# here is accepted). The limit is still enforced after the reply by the Pydantic model.
_KEPT_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minItems",
        "description",
    }
)
_MAX_DEPTH = 32

JsonSchema = dict[str, Any]


def provider_schema(model: type[Any]) -> JsonSchema:
    """The reduced, self-contained schema for ``model`` (a Pydantic model class)."""
    raw: JsonSchema = model.model_json_schema(mode="validation")
    definitions: JsonSchema = _object(raw.get("$defs"))
    return _reduce(_inline(raw, definitions, 0))


def _object(value: object) -> JsonSchema:
    return cast(JsonSchema, value) if isinstance(value, dict) else {}


def _inline(node: Any, definitions: JsonSchema, depth: int) -> Any:
    """Replace every ``$ref`` with the definition it points to."""
    if depth > _MAX_DEPTH:
        raise ValueError("schema is nested too deeply or refers to itself")
    if isinstance(node, list):
        return [_inline(item, definitions, depth + 1) for item in cast(list[Any], node)]
    if not isinstance(node, dict):
        return node
    mapping = cast(JsonSchema, node)
    reference = mapping.get("$ref")
    if isinstance(reference, str):
        name = reference.removeprefix("#/$defs/")
        if name not in definitions:
            raise ValueError(f"unresolved schema reference: {reference}")
        # Sibling keywords of a $ref (such as a field description) win over the definition.
        siblings = {key: value for key, value in mapping.items() if key != "$ref"}
        return _inline({**_object(definitions[name]), **siblings}, definitions, depth + 1)
    return {key: _inline(value, definitions, depth + 1) for key, value in mapping.items()}


def _reduce(node: Any) -> Any:
    """Keep only the supported keywords, recursively."""
    if isinstance(node, list):
        return [_reduce(item) for item in cast(list[Any], node)]
    if not isinstance(node, dict):
        return node
    current = _simplify_optional(cast(JsonSchema, node))
    if "const" in current and "enum" not in current:
        current = {**current, "enum": [current["const"]]}
    reduced: JsonSchema = {}
    for key, value in current.items():
        if key == "properties":
            reduced[key] = {name: _reduce(child) for name, child in _object(value).items()}
        elif key == "items":
            reduced[key] = _reduce(value)
        elif key in _KEPT_KEYWORDS:
            reduced[key] = value
    return reduced


def _simplify_optional(node: JsonSchema) -> JsonSchema:
    """``anyOf: [X, null]`` (Pydantic's ``X | None``) becomes ``X`` with ``type: [.., "null"]``."""
    options = node.get("anyOf")
    if not isinstance(options, list) or len(cast(list[Any], options)) != 2:
        return node
    candidates = [_object(option) for option in cast(list[Any], options)]
    nulls = [option for option in candidates if option.get("type") == "null"]
    others = [option for option in candidates if option.get("type") != "null"]
    if len(nulls) != 1 or len(others) != 1:
        return node
    inner = dict(others[0])
    kind = inner.get("type")
    if isinstance(kind, str):
        inner["type"] = [kind, "null"]
    outer = {key: value for key, value in node.items() if key != "anyOf"}
    return {**inner, **outer}
