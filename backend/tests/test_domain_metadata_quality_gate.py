from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate


def _quran_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        language="mixed",
        tags=["quran", "arabic", "english"],
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        custom_json={
            "reference_schema": {"type": "chapter_verse", "display": "{chapter}:{verse}"},
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
        },
        reference_pattern="surah_number:verse_number",
        script="mixed",
    )


def test_domain_quality_gate_uses_reference_metadata_when_text_lacks_reference_label():
    warnings = DomainMetadataQualityGate().warnings_for_text(
        "And affection from Us and purity, and he was fearing of Allah.",
        domain_metadata=_quran_metadata(),
        metadata={"reference_metadata": {"references": ["19:13"]}},
    )

    assert warnings == [
        {
            "code": "reference_unit_missing_expected_script",
            "message": (
                "Reference-bearing chunk is expected to contain Arabic script, "
                "but no Arabic letters were detected."
            ),
            "expected_script": "arabic",
        }
    ]


def test_domain_quality_gate_annotates_extraction_chunks_for_retrieval_time():
    chunks = [
        AdapterChunk(
            text="And affection from Us and purity, and he was fearing of Allah.",
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:13"]}},
        ),
        AdapterChunk(
            text=(
                "[1:1]\n\n"
                "\u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647\n\n"
                "All praise is due to Allah."
            ),
            source_location={"page": 1},
            metadata={"reference_metadata": {"references": ["1:1"]}},
        ),
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_quran_metadata(),
    )

    assert report["status"] == "passed_with_warnings"
    assert report["quality_profile"]["domain"] == "quran_tafseer"
    assert report["parser_quality"] == {
        "warning_counts": {"reference_unit_missing_expected_script": 1},
        "affected_chunks": 1,
    }
    assert chunks[0].metadata["extraction_quality"]["parser_warnings"][0][
        "expected_script"
    ] == "arabic"


def test_domain_quality_gate_builds_retrieval_trace_from_same_warning_shape():
    gate = DomainMetadataQualityGate()

    trace = gate.retrieval_trace(
        {"reference_unit_missing_expected_script": 2},
        ["metadata:chunk-1", "native:chunk-2"],
    )

    assert trace == {
        "stage": "parser_quality",
        "status": "warnings",
        "warning_counts": {"reference_unit_missing_expected_script": 2},
        "affected_candidate_ids": ["metadata:chunk-1", "native:chunk-2"],
    }
