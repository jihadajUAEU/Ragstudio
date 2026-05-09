from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

SAFE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9_?P<>()\[\]\{\}\\\^\$\.\:\-\+\*\s|]+$")
UNSAFE_PATTERN_TOKENS = ("(?=", "(?!", "(?<=", "(?<!", "(?:", "\\1", "\\2")


REFERENCE_CUSTOM_JSON_EXAMPLE: dict[str, Any] = {
    "reference_schema": {
        "type": "chapter_verse",
        "display": "{chapter}:{verse}",
        "fields": {
            "chapter": "chapter_number",
            "verse": "verse_number",
            "page": "page_number",
        },
    },
    "relationships": {
        "previous": ["same_chapter", "verse - 1"],
        "next": ["same_chapter", "verse + 1"],
        "chapter": ["same_chapter"],
        "page": ["same_page"],
    },
    "chunking": {
        "unit": "verse",
        "include_neighbors": 1,
        "preserve_parallel_text": True,
    },
    "retrieval": {
        "exact_reference_top1": True,
        "boost_same_chapter": True,
        "boost_neighbor_verses": True,
    },
    "graph": {
        "node_types": ["chapter", "verse", "chunk"],
        "edge_types": ["contains", "next", "references"],
        "materialize_from": ["mineru_structure", "reference_metadata"],
        "confidence_policy": "evidence_required",
    },
}


def validate_custom_json(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Custom JSON must be an object.")

    _validate_reference_schema(value.get("reference_schema"))
    _validate_relationships(value.get("relationships"))
    _validate_chunking(value.get("chunking"))
    _validate_retrieval(value.get("retrieval"))
    _validate_graph(value.get("graph"))
    return value


def reference_custom_json_example() -> dict[str, Any]:
    return deepcopy(REFERENCE_CUSTOM_JSON_EXAMPLE)


def _validate_reference_schema(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.reference_schema must be an object.")

    fields = value.get("fields")
    if fields is not None:
        if not isinstance(fields, dict):
            raise ValueError("custom_json.reference_schema.fields must be an object.")
        for key, field_value in fields.items():
            if not isinstance(key, str) or not isinstance(field_value, str):
                raise ValueError(
                    "custom_json.reference_schema.fields must map strings to strings."
                )

    for key in ("type", "display"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.reference_schema.{key} must be a string.")

    for key in ("pattern", "regex"):
        pattern = value.get(key)
        if pattern is None:
            continue
        _validate_reference_pattern(pattern, key)


def _validate_reference_pattern(pattern: Any, key: str) -> None:
    if not isinstance(pattern, str):
        raise ValueError(f"custom_json.reference_schema.{key} must be a string.")
    if len(pattern) > 160:
        raise ValueError(f"custom_json.reference_schema.{key} must be 160 characters or less.")
    if not SAFE_REFERENCE_PATTERN.match(pattern):
        raise ValueError(
            f"custom_json.reference_schema.{key} contains unsupported regex characters."
        )
    if any(token in pattern for token in UNSAFE_PATTERN_TOKENS):
        raise ValueError(
            f"custom_json.reference_schema.{key} contains unsupported regex constructs."
        )
    if re.search(r"\([^)]*(?:\+|\*|\{\d+,?\d*\})[^)]*\)\s*(?:\+|\*|\{)", pattern):
        raise ValueError(
            f"custom_json.reference_schema.{key} contains nested or adjacent quantifiers."
        )
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(
            f"custom_json.reference_schema.{key} must be a valid regex: {exc.msg}"
        ) from exc
    if not compiled.groupindex:
        raise ValueError(
            f"custom_json.reference_schema.{key} must include at least one named group."
        )


def _validate_relationships(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.relationships must be an object.")

    for key, relationships in value.items():
        if not isinstance(key, str):
            raise ValueError("custom_json.relationships keys must be strings.")
        if not isinstance(relationships, list) or not all(
            isinstance(item, str) for item in relationships
        ):
            raise ValueError("custom_json.relationships values must be lists of strings.")


def _validate_chunking(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.chunking must be an object.")

    unit = value.get("unit")
    if unit is not None and not isinstance(unit, str):
        raise ValueError("custom_json.chunking.unit must be a string.")

    include_neighbors = value.get("include_neighbors")
    if include_neighbors is not None:
        if isinstance(include_neighbors, bool) or not isinstance(include_neighbors, int):
            raise ValueError("custom_json.chunking.include_neighbors must be an integer.")
        if include_neighbors < 0:
            raise ValueError("custom_json.chunking.include_neighbors must be non-negative.")

    preserve_parallel_text = value.get("preserve_parallel_text")
    if preserve_parallel_text is not None and not isinstance(preserve_parallel_text, bool):
        raise ValueError("custom_json.chunking.preserve_parallel_text must be a boolean.")


def _validate_retrieval(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.retrieval must be an object.")

    for key, retrieval_value in value.items():
        if not isinstance(key, str):
            raise ValueError("custom_json.retrieval keys must be strings.")
        if not isinstance(retrieval_value, bool):
            raise ValueError("custom_json.retrieval values must be booleans.")


def _validate_graph(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.graph must be an object.")

    for key in ("node_types", "edge_types", "materialize_from"):
        _validate_string_list(value.get(key), f"custom_json.graph.{key}")

    confidence_policy = value.get("confidence_policy")
    if confidence_policy != "evidence_required":
        raise ValueError(
            "custom_json.graph.confidence_policy must be 'evidence_required'."
        )


def _validate_string_list(value: Any, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings.")
