from ragstudio.services.evidence_context import (
    evidence_context_from_metadata,
    prefixed_embedding_text,
)


def test_evidence_context_extracts_reference_section_and_layout():
    metadata = {
        "document_metadata": {"title": "Synthetic Tafseer"},
        "reference_metadata": {"references": ["1:5"]},
        "section_path": ["Surah Al-Fatihah", "Verse 5"],
        "content_type": "figure",
        "provenance": {
            "blocks": [
                {
                    "role": "caption",
                    "block_type": "image_caption",
                    "page_number": 3,
                    "bbox": [10, 20, 200, 60],
                }
            ]
        },
    }

    context = evidence_context_from_metadata(
        metadata,
        source_location={"page": 3},
        content_type="figure",
    )

    assert context["breadcrumb"] == "Synthetic Tafseer > Surah Al-Fatihah > Verse 5 > 1:5"
    assert context["layout_summary"] == "figure; page=3; block=image_caption; role=caption"
    assert context["page"] == 3
    assert context["reference"] == "1:5"


def test_prefixed_embedding_text_adds_context_once():
    text = "Guide us to the straight path."
    metadata = {
        "document_metadata": {"title": "Synthetic Tafseer"},
        "reference_metadata": {"references": ["1:5"]},
    }

    first = prefixed_embedding_text(text, metadata, source_location={"page": 1})
    second = prefixed_embedding_text(first, metadata, source_location={"page": 1})

    assert first.startswith("[Context: Synthetic Tafseer > 1:5]")
    assert second == first


def test_evidence_context_uses_first_available_path_family():
    metadata = {
        "document_metadata": {"title": "Synthetic Tafseer"},
        "reference_metadata": {"references": ["1:5"]},
        "section_path": ["Section A"],
        "heading_path": ["Heading B"],
        "breadcrumbs": ["Crumb C"],
    }

    context = evidence_context_from_metadata(metadata)

    assert context["breadcrumb"] == "Synthetic Tafseer > Section A > 1:5"
