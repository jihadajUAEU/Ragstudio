from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.layout_auto_repair import LayoutAutoRepairService


def test_layout_auto_repair_promotes_single_page_to_range() -> None:
    chunk = AdapterChunk(
        text="Chunk text",
        source_location={"page": 7, "artifact": "content_list.json"},
        metadata={"parser_metadata": {"backend": "mineru"}},
    )

    result = LayoutAutoRepairService().repair([chunk])

    repaired = result.chunks[0]
    assert repaired.source_location == {
        "page_start": 7,
        "page_end": 7,
        "artifact": "content_list.json",
    }
    assert result.repaired_count == 1
    assert result.diagnostics[0].code == "single_page_promoted_to_range"
    assert repaired.metadata["layout_auto_repair"]["diagnostics"][0]["code"] == (
        "single_page_promoted_to_range"
    )
    assert repaired.text == chunk.text


def test_layout_auto_repair_reorders_inverted_page_range_without_content_changes() -> None:
    chunk = AdapterChunk(
        text="Existing content",
        source_location={"page_start": 12, "page_end": 10, "page": 12},
        metadata={"existing": True},
        runtime_source_id="runtime-1",
        content_type="text",
        preview_ref="preview://runtime-1",
    )

    result = LayoutAutoRepairService().repair([chunk])

    repaired = result.chunks[0]
    assert repaired.source_location == {"page_start": 10, "page_end": 12}
    assert repaired.text == "Existing content"
    assert repaired.runtime_source_id == "runtime-1"
    assert repaired.preview_ref == "preview://runtime-1"
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "page_range_reordered"
    ]
    assert repaired.metadata["existing"] is True


def test_layout_auto_repair_leaves_clean_or_unsupported_metadata_unchanged() -> None:
    clean = AdapterChunk(
        text="Clean",
        source_location={"page_start": 1, "page_end": 2},
        metadata={"parser_metadata": {"backend": "mineru"}},
    )
    unsupported = AdapterChunk(
        text="Unsupported",
        source_location={"page": "3"},
        metadata={},
    )

    result = LayoutAutoRepairService().repair([clean, unsupported])

    assert result.chunks == [clean, unsupported]
    assert result.diagnostics == []
    assert result.diagnostics_payload() == {
        "version": 1,
        "strategy": "local_layout_auto_repair",
        "repaired_count": 0,
        "diagnostics": [],
    }
