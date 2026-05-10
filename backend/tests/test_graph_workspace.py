from types import SimpleNamespace

from ragstudio.services.graph_workspace import (
    chunk_graph_id,
    graph_relationship_type,
    reference_graph_id,
    workspace_label,
)


def test_workspace_label_sanitizes_profile_id():
    profile = SimpleNamespace(id="tenant` one")

    assert workspace_label(profile) == "ragstudio_tenant__one"


def test_workspace_label_defaults_when_profile_id_is_missing():
    profile = SimpleNamespace()

    assert workspace_label(profile) == "ragstudio_default"


def test_chunk_graph_id_is_stable_for_persisted_chunk():
    assert chunk_graph_id(document_id="doc-1", chunk_id="chunk-9") == "chunk:doc-1:chunk-9"


def test_reference_graph_id_scopes_reference_to_document():
    assert (
        reference_graph_id(document_id="doc-1", reference="book:53:hadith:17")
        == "ref:doc-1:book:53:hadith:17"
    )
    assert (
        reference_graph_id(document_id="doc-1", reference="ref:book:53:hadith:17")
        == "ref:doc-1:book:53:hadith:17"
    )


def test_graph_relationship_type_is_neo4j_safe():
    assert graph_relationship_type("next_hadith") == "NEXT_HADITH"
    assert graph_relationship_type("same-book") == "SAME_BOOK"
    assert graph_relationship_type(" references ") == "REFERENCES"
