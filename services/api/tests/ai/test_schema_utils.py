"""The schema sent to the model: self-contained and limited to keywords Gemini documents."""

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from app.ai.roadmap.schema import PlannedRoadmap
from app.ai.schema_utils import provider_schema

SUPPORTED = {
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


def all_keywords(node: Any) -> set[str]:
    """Every JSON Schema keyword used, ignoring property names (which are data)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in cast(dict[str, Any], node).items():
            found.add(key)
            if key == "properties" and isinstance(value, dict):
                for child in cast(dict[str, Any], value).values():
                    found |= all_keywords(child)
            else:
                found |= all_keywords(value)
    elif isinstance(node, list):
        for item in cast(list[Any], node):
            found |= all_keywords(item)
    return found


def test_the_roadmap_schema_uses_only_documented_keywords() -> None:
    schema = provider_schema(PlannedRoadmap)

    assert all_keywords(schema) <= SUPPORTED


def test_the_roadmap_schema_is_self_contained() -> None:
    text = json.dumps(provider_schema(PlannedRoadmap))

    assert "$ref" not in text
    assert "$defs" not in text


def test_nested_models_are_inlined_with_their_fields() -> None:
    schema = provider_schema(PlannedRoadmap)

    topic = schema["properties"]["modules"]["items"]["properties"]["topics"]["items"]
    assert topic["type"] == "object"
    assert {"key", "day", "estimated_minutes", "prerequisite_keys"} <= set(topic["properties"])
    assert "key" in topic["required"]
    assert "prerequisite_keys" not in topic["required"]  # has a default


def test_field_descriptions_and_numeric_limits_are_kept_as_guidance() -> None:
    schema = provider_schema(PlannedRoadmap)

    day = schema["properties"]["modules"]["items"]["properties"]["topics"]["items"]["properties"][
        "day"
    ]
    assert day["type"] == "integer"
    assert day["minimum"] == 1
    assert "study day" in day["description"]


def test_optional_fields_become_a_type_list_with_null() -> None:
    class Sample(BaseModel):
        note: str | None = None
        count: int = Field(default=1, ge=0, le=5)

    schema = provider_schema(Sample)

    assert schema["properties"]["note"]["type"] == ["string", "null"]
    assert schema["properties"]["count"] == {"type": "integer", "minimum": 0, "maximum": 5}


def test_literals_become_enums() -> None:
    class Sample(BaseModel):
        basis: Literal["a", "b"]
        fixed: Literal["only"]

    schema = provider_schema(Sample)

    assert schema["properties"]["basis"]["enum"] == ["a", "b"]
    assert schema["properties"]["fixed"]["enum"] == ["only"]


def test_array_size_limits_are_not_sent_because_the_live_api_rejects_them() -> None:
    """Gemini answered a bare 400 for the roadmap schema until ``maxItems`` was dropped."""

    class Sample(BaseModel):
        items: list[str] = Field(min_length=1, max_length=3)

    schema = provider_schema(Sample)

    assert "maxItems" not in all_keywords(schema)
    assert schema["properties"]["items"]["minItems"] == 1
    assert "maxItems" not in json.dumps(provider_schema(PlannedRoadmap))
