from __future__ import annotations

from typing import Any


def workspace_label(profile: Any) -> str:
    raw = f"ragstudio_{getattr(profile, 'id', 'default')}"
    safe = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw
    ).strip("_")
    return (safe or "ragstudio_default").replace("`", "``")


def chunk_graph_id(*, document_id: str, chunk_id: str) -> str:
    return f"chunk:{document_id}:{chunk_id}"


def reference_graph_id(*, document_id: str, reference: str) -> str:
    normalized = reference.strip()
    if normalized.startswith("ref:"):
        normalized = normalized.removeprefix("ref:")
    return f"ref:{document_id}:{normalized}"


def graph_relationship_type(value: str) -> str:
    normalized = value.strip().replace("-", "_").replace(" ", "_")
    safe = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in normalized
    )
    collapsed = "_".join(part for part in safe.split("_") if part)
    return (collapsed or "RELATED").upper()
