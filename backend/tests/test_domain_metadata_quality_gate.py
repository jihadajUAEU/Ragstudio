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


def test_domain_quality_gate_reports_canonical_reference_units_for_quran_19_13():
    chunks = [
        AdapterChunk(
            text=(
                "[19:12] \u064a\u0627 \u064a\u062d\u064a\u0649 "
                "\u062e\u0630 \u0627\u0644\u0643\u062a\u0627\u0628 "
                "O John, take the Scripture."
            ),
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:12"]}},
        ),
        AdapterChunk(
            text="[19:13] And affection from Us and purity, and he was fearing of Allah.",
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:13"]}},
        ),
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_quran_metadata(),
    )

    references = {
        item["reference"]: item for item in report["index_quality_report"]["references"]
    }
    assert references["19:12"]["status"] == "passed"
    assert references["19:13"]["status"] == "missing_expected_script"
    assert references["19:13"]["missing_scripts"] == ["arabic"]
    assert references["19:13"]["materialization"]["index_exact_arabic"] is False
    assert chunks[1].metadata["quality_action_policy"]["index_vector"] is False


def test_domain_quality_gate_prevents_multi_reference_arabic_masking():
    chunks = [
        AdapterChunk(
            text=(
                "[19:12] \u064a\u0627 \u064a\u062d\u064a\u0649 "
                "\u062e\u0630 \u0627\u0644\u0643\u062a\u0627\u0628 "
                "O John, take the Scripture strongly.\n\n"
                "[19:13] And affection from Us and purity, and he was fearing of Allah."
            ),
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:12", "19:13"]}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_quran_metadata(),
    )

    by_reference = {
        item["reference"]: item for item in chunks[0].metadata["quality"]["by_reference"]
    }
    assert by_reference["19:12"]["status"] == "passed"
    assert by_reference["19:13"]["status"] == "missing_expected_script"
    assert by_reference["19:13"]["arabic_token_count"] == 0
    assert report["index_quality_report"]["summary"][
        "reference_units_missing_expected_script"
    ] == 1


def test_domain_quality_gate_flags_structured_chunks_without_reference_metadata():
    chunks = [
        AdapterChunk(
            text=(
                "[19:12] \u064a\u0627 \u064a\u062d\u064a\u0649 "
                "\u062e\u0630 \u0627\u0644\u0643\u062a\u0627\u0628 "
                "O John, take the Scripture."
            ),
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:12"]}},
        ),
        AdapterChunk(
            text="And affection from Us and purity, and he was fearing of Allah.",
            source_location={"page": 312},
            metadata={},
        ),
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_quran_metadata(),
    )

    unresolved = report["index_quality_report"]["unresolved"]
    assert unresolved[0]["status"] == "unresolved"
    assert unresolved[0]["quality_flags"] == ["reference_unit_unresolved"]
    assert chunks[1].metadata["quality_action_policy"]["project_graph"] is False
    warning_codes = [
        warning["code"]
        for warning in chunks[1].metadata["extraction_quality"]["parser_warnings"]
    ]
    assert "reference_unit_unresolved" in warning_codes


def test_domain_quality_gate_treats_reference_provenance_as_non_answerable():
    chunks = [
        AdapterChunk(
            text=(
                "[19:13] "
                "\u0648\u062d\u0646\u0627\u0646\u0627 "
                "\u0645\u0646 \u0644\u062f\u0646\u0627 "
                "And affection from Us."
            ),
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:13"]}},
        ),
        AdapterChunk(
            text="[19:14]",
            source_location={"page": 312},
            metadata={
                "parser_metadata": {"provenance_only": True},
                "reference_metadata": {"references": ["19:14"]},
            },
            content_type="reference_provenance",
        ),
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_quran_metadata(),
    )

    summary = report["index_quality_report"]["summary"]
    assert summary["reference_unit_count"] == 1
    assert summary["reference_unit_unresolved_count"] == 0
    assert summary["reference_units_missing_expected_script"] == 0
    assert chunks[1].metadata["quality_action_policy"] == {
        "persist_chunk": True,
        "index_vector": False,
        "index_exact_arabic": False,
        "project_graph": False,
        "graph_confidence": "provenance_only",
        "quality_flags": ["provenance_only"],
    }
    assert "extraction_quality" not in chunks[1].metadata


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
