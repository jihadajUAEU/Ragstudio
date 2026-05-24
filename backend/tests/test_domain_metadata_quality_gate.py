import pytest
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
            "quality_policy": {
                "required_scripts": ["arabic"],
                "missing_required_script_action": "warn",
            },
        },
        reference_pattern="surah_number:verse_number",
        script="mixed",
    )


def _tafseer_quality_policy_metadata(
    *,
    missing_optional_script_action: str = "no_warning",
    layout_action: str = "recover_as_text",
    layout_warning_level: str = "info",
) -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        content_role="tafseer",
        tags=["quran", "tafseer", "english"],
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        reference_pattern="surah_number:verse_number",
        script="mixed",
        custom_json={
            "reference_schema": {"type": "chapter_verse", "display": "{chapter}:{verse}"},
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                    "unit": "verse_section",
                },
                "inline_references": {
                    "type": "chapter_verse",
                    "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                    "policy": "cross_reference_only",
                },
            },
            "quality_policy": {
                "document_role": "commentary",
                "observed_scripts": ["arabic", "latin"],
                "required_scripts": ["latin"],
                "optional_scripts": ["arabic"],
                "missing_required_script_action": "warn",
                "missing_optional_script_action": missing_optional_script_action,
                "materialization_policy": "allow_if_required_scripts_present",
            },
            "layout_quality_policy": {
                "misclassified_block_policy": {
                    "equation_with_recovered_text": {
                        "action": layout_action,
                        "warning_level": layout_warning_level,
                    }
                }
            },
        },
    )


def _optional_only_quality_policy_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        content_role="tafseer",
        tags=["quran", "tafseer", "english"],
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        reference_pattern="surah_number:verse_number",
        script="mixed",
        custom_json={
            "reference_schema": {"type": "chapter_verse", "display": "{chapter}:{verse}"},
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
            "quality_policy": {
                "document_role": "commentary",
                "required_scripts": [],
                "optional_scripts": ["arabic"],
                "missing_optional_script_action": "block",
                "materialization_policy": "allow_if_required_scripts_present",
            },
        },
    )


def test_parser_quality_details_separates_counted_warnings_from_audit_rows():
    chunk = AdapterChunk(
        text="[19:13] And affection from Us and purity.",
        source_location={"page": 412},
        metadata={
            "extraction_quality": {
                "parser_warnings": [
                    {
                        "code": "reference_unit_missing_expected_script",
                        "message": "Missing Arabic script.",
                        "expected_script": "arabic",
                    },
                    {
                        "code": "reference_unit_missing_expected_script",
                        "message": "Missing Arabic script.",
                        "reference": "19:13",
                        "expected_script": "arabic",
                        "severity": "info",
                        "suppressed_from_counts": True,
                        "vision_recovery_status": "succeeded",
                    },
                ]
            }
        },
    )

    details = DomainMetadataQualityGate().parser_quality_details([chunk])

    assert len(details["groups"]) == 1
    group = details["groups"][0]
    assert group["code"] == "reference_unit_missing_expected_script"
    assert group["warning_count"] == 0
    assert group["chunk_count"] == 0
    assert group["raw_warning_count"] == 1
    assert group["raw_chunk_count"] == 1
    assert group["vision_recovery_statuses"] == {"succeeded": 1}


def _role_scoped_quality_policy_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        content_role="tafseer",
        tags=["quran", "tafseer", "english"],
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        reference_pattern="surah_number:verse_number",
        script="mixed",
        custom_json={
            "reference_schema": {"type": "chapter_verse", "display": "{chapter}:{verse}"},
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
            "quality_policy": {
                "document_role": "commentary",
                "required_scripts": [],
                "optional_scripts": [],
                "required_scripts_by_unit_role": {"verse_section": ["latin"]},
                "optional_scripts_by_unit_role": {"commentary": ["arabic"]},
                "missing_required_script_action": "warn",
                "missing_optional_script_action": "block",
                "materialization_policy": "allow_if_required_scripts_present",
            },
        },
    )


def _hadith_quality_policy_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="mixed",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "quality_policy": {
                "required_scripts": ["arabic"],
                "optional_scripts": ["latin"],
                "required_scripts_by_unit_role": {"hadith": ["arabic"]},
                "optional_scripts_by_unit_role": {"hadith": ["latin"]},
                "missing_optional_script_action": "no_warning",
                "missing_required_script_action": "warn",
                "materialization_policy": "allow_if_required_scripts_present",
            },
        },
    )


def test_domain_quality_gate_uses_canonical_hadith_reference_before_inline_verse():
    chunks = [
        AdapterChunk(
            text=(
                "Book 5, Hadith 14\n\n"
                "\u0633\u0645\u0639 \u0627\u0644\u0646\u0628\u064a \u064a\u0642\u0631\u0623 "
                "\u0641\u064a \u0627\u0644\u0635\u0628\u062d. "
                "It was narrated that he recited [50:10] in the Subh."
            ),
            source_location={"page": 169},
            metadata={
                "reference_metadata": {"references": ["book:5:hadith:14"]},
                "canonical_reference_unit": {
                    "reference": "book:5:hadith:14",
                    "unit": "hadith",
                    "answerable": True,
                    "body_status": "assembled",
                },
            },
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_hadith_quality_policy_metadata(),
    )

    assert report["status"] == "passed"
    assert report["parser_quality"]["warning_counts"] == {}
    assert "extraction_quality" not in chunks[0].metadata
    references = report["index_quality_report"]["references"]
    assert [record["reference"] for record in references] == ["book:5:hadith:14"]


def test_domain_quality_gate_uses_canonical_reference_for_any_structured_domain():
    chunks = [
        AdapterChunk(
            text=(
                "Verse 18:30\n\n"
                "Indeed, those who believed will have gardens. "
                "The explanation also mentions 25:75-76."
            ),
            source_location={"page": 809},
            metadata={
                "reference_metadata": {
                    "references": ["18:30"],
                    "cross_references": ["25:75"],
                },
                "canonical_reference_unit": {
                    "reference": "18:30",
                    "unit": "verse_section",
                    "answerable": True,
                    "body_status": "assembled",
                },
            },
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(),
    )

    assert report["status"] == "passed"
    assert report["parser_quality"]["warning_counts"] == {}
    references = report["index_quality_report"]["references"]
    assert [record["reference"] for record in references] == ["18:30"]


def test_domain_quality_gate_allows_tafseer_commentary_when_optional_arabic_is_missing():
    chunks = [
        AdapterChunk(
            text=(
                "Verse 18:30 Indeed, those who have believed and done righteous deeds. "
                "The Tafseer explains the reward and references 25:75-76."
            ),
            source_location={"page": 809},
            metadata={"reference_metadata": {"references": ["18:30"]}},
        )
    ]

    gate = DomainMetadataQualityGate()
    report = gate.validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(),
    )

    assert report["status"] == "passed"
    assert report["parser_quality"]["warning_counts"] == {}
    assert report["index_quality_report"]["summary"][
        "reference_units_missing_expected_script"
    ] == 0
    assert "extraction_quality" not in chunks[0].metadata
    assert chunks[0].metadata["quality_action_policy"]["index_vector"] is True
    assert chunks[0].metadata["quality_action_policy"]["project_graph"] is True


def test_domain_quality_gate_still_warns_when_required_latin_is_missing():
    chunks = [
        AdapterChunk(
            text="18:30",
            source_location={"page": 809},
            metadata={"reference_metadata": {"references": ["18:30"]}},
        )
    ]

    gate = DomainMetadataQualityGate()
    report = gate.validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(),
    )

    assert report["status"] == "passed_with_warnings"
    warnings = chunks[0].metadata["extraction_quality"]["parser_warnings"]
    assert warnings[0]["code"] == "reference_unit_missing_expected_script"
    assert warnings[0]["expected_script"] == "latin"


def test_domain_quality_gate_suppresses_accepted_recovered_text_warning_counts():
    chunks = [
        AdapterChunk(
            text="Verse 18:30 Indeed, those who have believed.",
            source_location={"page": 809},
            metadata={
                "reference_metadata": {"references": ["18:30"]},
                "extraction_quality": {
                    "parser_warnings": [
                        {
                            "code": "recovered_text_from_misclassified_block",
                            "block_type": "equation",
                            "message": "Used parser-provided recovered text.",
                        }
                    ]
                },
            },
        )
    ]

    gate = DomainMetadataQualityGate()
    report = gate.validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(),
    )

    assert report["status"] == "passed"
    warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
    assert warning["severity"] == "info"
    assert warning["quality_gate_action"] == "accepted_recovery"
    assert warning["suppressed_from_counts"] is True
    assert gate.parser_warning_codes(chunks[0].metadata) == []
    assert gate.parser_warning_codes_for_chunk(chunks[0]) == []


@pytest.mark.parametrize(
    ("layout_action", "layout_warning_level"),
    [("block", "warn"), ("block", "info"), ("recover_as_text", "block")],
)
def test_domain_quality_gate_blocks_layout_policy_materialization(
    layout_action: str,
    layout_warning_level: str,
):
    chunks = [
        AdapterChunk(
            text="Verse 18:30 Indeed, those who have believed.",
            source_location={"page": 809},
            metadata={
                "reference_metadata": {"references": ["18:30"]},
                "extraction_quality": {
                    "parser_warnings": [
                        {
                            "code": "recovered_text_from_misclassified_block",
                            "block_type": "equation",
                            "message": "Used parser-provided recovered text.",
                        }
                    ]
                },
            },
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(
            layout_action=layout_action,
            layout_warning_level=layout_warning_level,
        ),
    )

    warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
    policy = chunks[0].metadata["quality_action_policy"]
    assert report["status"] == "passed_with_warnings"
    assert warning["suppressed_from_counts"] is False
    assert policy["index_vector"] is False
    assert policy["project_graph"] is False
    assert policy["graph_confidence"] == "blocked"
    assert "parser_quality_block:recovered_text_from_misclassified_block" in policy[
        "quality_flags"
    ]


def test_domain_quality_gate_persists_modal_table_warning():
    chunks = [
        AdapterChunk(
            text=" ",
            source_location={"page": 1},
            metadata={"modality": "table", "structured_data": {}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=DomainMetadata(domain="generic", language="english"),
    )

    warnings = chunks[0].metadata["extraction_quality"]["parser_warnings"]
    policy = chunks[0].metadata["quality_action_policy"]
    assert report["status"] == "passed_with_warnings"
    assert report["modal_validation"] == warnings
    assert warnings[0]["code"] == "table_missing_structure"
    assert warnings[0]["severity"] == "block"
    assert warnings[0]["quality_gate_action"] == "block"
    assert policy["index_vector"] is False
    assert policy["project_graph"] is False
    assert "parser_quality_block:table_missing_structure" in policy["quality_flags"]


def test_domain_quality_gate_persists_modal_image_warning():
    chunks = [
        AdapterChunk(
            text=" ",
            source_location={"page": 1},
            metadata={"modality": "image", "structured_data": {"caption": []}},
        )
    ]

    DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=DomainMetadata(domain="generic", language="english"),
    )

    warnings = chunks[0].metadata["extraction_quality"]["parser_warnings"]
    assert warnings[0]["code"] == "image_missing_description"
    assert warnings[0]["source"] == "modal_validation"


def test_domain_quality_gate_warns_when_optional_script_action_is_warn():
    chunks = [
        AdapterChunk(
            text="Verse 18:30 Indeed, those who have believed.",
            source_location={"page": 809},
            metadata={"reference_metadata": {"references": ["18:30"]}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(
            missing_optional_script_action="warn"
        ),
    )

    warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
    assert report["status"] == "passed_with_warnings"
    assert report["index_quality_report"]["summary"][
        "reference_units_missing_optional_script"
    ] == 1
    assert warning["code"] == "reference_unit_missing_optional_script"
    assert warning["expected_script"] == "arabic"
    assert warning["severity"] == "warn"
    assert warning["suppressed_from_counts"] is False
    assert chunks[0].metadata["quality_action_policy"]["index_vector"] is True
    assert chunks[0].metadata["quality_action_policy"]["project_graph"] is True


def test_domain_quality_gate_blocks_when_optional_script_action_is_block():
    chunks = [
        AdapterChunk(
            text="Verse 18:30 Indeed, those who have believed.",
            source_location={"page": 809},
            metadata={"reference_metadata": {"references": ["18:30"]}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(
            missing_optional_script_action="block"
        ),
    )

    warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
    policy = chunks[0].metadata["quality_action_policy"]
    assert report["status"] == "passed_with_warnings"
    assert warning["code"] == "reference_unit_missing_optional_script"
    assert warning["severity"] == "block"
    assert policy["index_vector"] is False
    assert policy["project_graph"] is False
    assert "missing_optional_script:arabic" in policy["quality_flags"]


def test_domain_quality_gate_blocks_optional_only_policy_without_required_scripts():
    chunks = [
        AdapterChunk(
            text="Verse 18:30 Indeed, those who have believed.",
            source_location={"page": 809},
            metadata={"reference_metadata": {"references": ["18:30"]}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_optional_only_quality_policy_metadata(),
    )

    warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
    policy = chunks[0].metadata["quality_action_policy"]
    summary = report["index_quality_report"]["summary"]
    assert report["status"] == "passed_with_warnings"
    assert summary["reference_units_missing_expected_script"] == 0
    assert summary["reference_units_missing_optional_script"] == 1
    assert summary["materialization_blocked_reference_count"] == 1
    assert warning["code"] == "reference_unit_missing_optional_script"
    assert warning["severity"] == "block"
    assert warning["suppressed_from_counts"] is False
    assert policy["index_vector"] is False
    assert policy["project_graph"] is False
    assert policy["graph_confidence"] == "blocked"


def test_quality_gate_does_not_require_global_arabic_when_role_marks_it_optional():
    metadata = DomainMetadata(
        domain="translation",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "chunking": {"unit": "verse_translation"},
            "quality_policy": {
                "required_scripts": [],
                "optional_scripts_by_unit_role": {"verse_translation": ["arabic"]},
                "missing_optional_script_action": "no_warning",
            },
        },
    )
    chunk = AdapterChunk(
        text="[1:4]\nIt is You we worship and You we ask for help.",
        source_location={"page": 2, "reference": "1:4"},
        metadata={"canonical_reference_unit": {"unit_role": "verse_translation"}},
    )

    DomainMetadataQualityGate().annotate_chunk(chunk, domain_metadata=metadata)

    warnings = chunk.metadata.get("extraction_quality", {}).get("parser_warnings", [])
    assert all(
        warning["code"] != "reference_unit_missing_expected_script"
        for warning in warnings
    )


def test_quality_gate_does_not_hard_fail_quran_language_when_arabic_is_optional():
    metadata = DomainMetadata(
        domain="translation",
        language="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "chunking": {"unit": "verse_translation"},
            "quality_policy": {
                "required_scripts": [],
                "optional_scripts_by_unit_role": {"verse_translation": ["arabic"]},
                "missing_optional_script_action": "no_warning",
            },
        },
    )
    chunk = AdapterChunk(
        text="[1:4]\nIt is You we worship and You we ask for help.",
        source_location={"page": 2, "reference": "1:4"},
        metadata={
            "reference_metadata": {"references": ["1:4"]},
            "canonical_reference_unit": {"unit_role": "verse_translation"},
        },
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        language="quran",
        domain_metadata=metadata,
    )

    assert report["status"] == "passed"
    assert "extraction_quality" not in chunk.metadata


def test_domain_quality_gate_consumes_role_scoped_script_policies():
    chunks = [
        AdapterChunk(
            text="18:30",
            source_location={"page": 809},
            metadata={
                "reference_metadata": {"references": ["18:30"]},
                "canonical_reference_unit": {"unit": "verse_section"},
            },
        ),
        AdapterChunk(
            text="18:31 Commentary in English only.",
            source_location={"page": 810},
            metadata={
                "reference_metadata": {"references": ["18:31"]},
                "canonical_reference_unit": {"unit_role": "commentary"},
            },
        ),
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_role_scoped_quality_policy_metadata(),
    )

    records = {
        record["reference"]: record
        for record in report["index_quality_report"]["references"]
    }
    assert records["18:30"]["unit_role"] == "verse_section"
    assert records["18:30"]["expected_scripts"] == ["latin"]
    assert records["18:30"]["status"] == "missing_expected_script"
    assert records["18:31"]["unit_role"] == "commentary"
    assert records["18:31"]["expected_scripts"] == ["arabic"]
    assert records["18:31"]["status"] == "missing_optional_script"
    assert chunks[1].metadata["quality_action_policy"]["index_vector"] is False
    assert chunks[1].metadata["quality_action_policy"]["project_graph"] is False


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


def test_domain_quality_gate_does_not_use_builtin_reference_fallback_for_contextual_contract():
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": r"\bSurah\s+(?P<chapter>\d{1,4})\b",
                    "unit": "chapter",
                    "verified": True,
                },
                "unit_anchor": {
                    "regex": r"\bAyah\s+(?P<verse>\d{1,4})\b",
                    "unit": "verse",
                    "context_source": "context_anchor",
                    "verified": True,
                },
            },
            "quality_policy": {
                "optional_scripts": ["arabic"],
                "missing_optional_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="Cross reference only 7:104",
        source_location={"page": 4},
        metadata={},
    )

    warnings = DomainMetadataQualityGate().warnings_for_text(
        chunk.text,
        domain_metadata=metadata,
    )
    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert warnings == []
    assert "reference_unit_missing_expected_script" not in report["parser_quality"][
        "warning_counts"
    ]
    assert "reference_unit_missing_optional_script" not in report["parser_quality"][
        "warning_counts"
    ]
    assert {
        record.get("reference")
        for record in report["index_quality_report"]["references"]
    } == set()


def test_domain_quality_gate_uses_valid_contextual_contract_units():
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": r"\bSurah\s+(?P<chapter>\d{1,4})\b",
                    "unit": "chapter",
                    "verified": True,
                },
                "unit_anchor": {
                    "regex": r"\bAyah\s+(?P<verse>\d{1,4})\b",
                    "unit": "verse",
                    "context_source": "context_anchor",
                    "verified": True,
                },
            },
            "quality_policy": {
                "optional_scripts": ["arabic"],
                "missing_optional_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="Surah 7\nAyah 104 Moses said...",
        source_location={"page": 4},
        metadata={},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    records = report["index_quality_report"]["references"]
    assert [record["reference"] for record in records] == ["7:104"]
    assert records[0]["unit_role"] == "verse"
    assert records[0]["status"] == "missing_optional_script"


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
    warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
    assert warning["vision_recovery_required"] is True
    assert warning["repair"]["vision_recovery"]["scope"] == "reference_unit"
    assert chunks[0].metadata["quality_repair"][
        "targeted_vision_recovery_requests"
    ][0]["reference"] == "19:13"


def test_domain_quality_gate_repairs_missing_script_from_same_chunk_provenance():
    chunks = [
        AdapterChunk(
            text="[19:13] And affection from Us and purity.",
            source_location={"page": 312},
            metadata={
                "reference_metadata": {"references": ["19:13"]},
                "provenance": {
                    "blocks": [
                        {
                            "role": "reference_body",
                            "block_type": "text",
                            "text_preview": (
                                "\u0648\u062d\u0646\u0627\u0646\u0627 "
                                "\u0645\u0646 \u0644\u062f\u0646\u0627"
                            ),
                        }
                    ]
                },
            },
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_quran_metadata(),
    )

    assert report["status"] == "passed"
    assert report["quality_repair"]["local_script_repairs"] == 1
    assert report["parser_quality"]["warning_counts"] == {}
    assert "\u0648\u062d\u0646\u0627\u0646\u0627" in chunks[0].text
    assert chunks[0].metadata["quality_repair"]["local_script_repair"]["status"] == "applied"


def test_domain_quality_gate_downgrades_pure_layout_noise_to_info():
    chunks = [
        AdapterChunk(
            text=(
                "[1:1] \u0627\u0644\u062d\u0645\u062f "
                "\u0644\u0644\u0647 All praise is due to Allah."
            ),
            source_location={"page": 1},
            metadata={
                "reference_metadata": {"references": ["1:1"]},
                "extraction_quality": {
                    "parser_warnings": [
                        {
                            "code": "disallowed_block_type_quarantined",
                            "block_type": "header",
                            "message": "Header was quarantined.",
                        }
                    ]
                },
            },
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_quran_metadata(),
    )

    warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
    assert report["status"] == "passed"
    assert report["quality_repair"]["layout_noise_downgrades"] == 1
    assert report["parser_quality"]["warning_counts"] == {}
    assert warning["severity"] == "info"
    assert warning["suppressed_from_counts"] is True
    assert warning["quality_gate_action"] == "provenance_only_layout_noise"


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


@pytest.mark.parametrize(
    "contract_fields",
    [
        {"contract_status": "metadata_only"},
        {"reference_contract": {"verified": False, "anchors": [], "canonical_units": False}},
        {
            "reference_contract_validation": {
                "status": "unverified",
                "selected_source": None,
                "selected_strategy": None,
                "matched_units": 0,
                "matched_pages": [],
                "candidates": [],
            }
        },
    ],
)
def test_unverified_reference_schema_does_not_emit_reference_unit_unresolved(contract_fields):
    metadata = DomainMetadata(
        domain="policy",
        document_type="insurance_policy",
        language="mixed",
        custom_json={
            "reference_schema": {
                "type": "bilingual_section_numbering",
                "fields": {"clause": "clause"},
                "canonical_ref_template": "{clause}",
            },
            **contract_fields,
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"^(?:Clause|البند)\s+(?P<clause>\d+)",
                    "unit": "clause",
                    "verified": False,
                }
            },
            "quality_policy": {
                "required_scripts": ["latin"],
                "missing_required_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="Definitions and general terms without a clause anchor.",
        source_location={"page": 1},
        metadata={},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert "reference_unit_unresolved" not in report["parser_quality"]["warning_counts"]
    assert report["index_quality_report"]["summary"]["reference_unit_unresolved_count"] == 0


def test_metadata_only_reference_hints_keep_independent_script_materialization_gate():
    metadata = DomainMetadata(
        domain="policy",
        document_type="insurance_policy",
        language="mixed",
        custom_json={
            "reference_schema": {
                "type": "bilingual_section_numbering",
                "fields": {"clause": "clause"},
                "canonical_ref_template": "{clause}",
            },
            "contract_status": "metadata_only",
            "quality_policy": {
                "required_scripts": ["latin"],
                "missing_required_script_action": "block",
                "materialization_policy": "block_if_required_scripts_missing",
            },
        },
    )
    chunk = AdapterChunk(
        text="البند 12 تعريفات وشروط عامة.",
        source_location={"page": 1, "reference": "12"},
        metadata={"reference_metadata": {"references": ["12"]}},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert report["parser_quality"]["warning_counts"] == {
        "reference_unit_missing_expected_script": 1
    }
    assert report["index_quality_report"]["summary"][
        "reference_units_missing_expected_script"
    ] == 1
    assert report["index_quality_report"]["summary"]["reference_unit_unresolved_count"] == 0
    policy = chunk.metadata["quality_action_policy"]
    assert policy["index_vector"] is False
    assert policy["project_graph"] is False
    assert "missing_expected_script:latin" in policy["quality_flags"]


def test_verified_reference_contract_still_enforces_unresolved_reference_units():
    metadata = DomainMetadata(
        domain="policy",
        document_type="insurance_policy",
        language="mixed",
        custom_json={
            "reference_schema": {
                "type": "bilingual_section_numbering",
                "fields": {"clause": "clause"},
                "canonical_ref_template": "{clause}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"^(?:Clause|البند)\s+(?P<clause>\d+)",
                    "unit": "clause",
                    "verified": True,
                }
            },
            "quality_policy": {
                "required_scripts": ["latin"],
                "missing_required_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="Definitions and general terms without a clause anchor.",
        source_location={"page": 1},
        metadata={},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert report["parser_quality"]["warning_counts"]["reference_unit_unresolved"] == 1
    assert report["index_quality_report"]["summary"]["reference_unit_unresolved_count"] == 1
