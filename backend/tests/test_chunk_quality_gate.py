from ragstudio.services.chunk_quality_gate import ChunkQualityGate
from ragstudio.services.parser_normalization import ExpectedContentProfile


def test_quality_gate_flags_reference_unit_missing_expected_arabic_script():
    gate = ChunkQualityGate(
        ExpectedContentProfile(
            expected_scripts=frozenset({"arabic"}),
            reference_patterns=(r"Book\s+\d+,\s*Hadith\s+\d+",),
        )
    )

    warnings = gate.warnings_for("Book 1, Hadith 2\n\nEnglish translation only.")

    assert [warning["code"] for warning in warnings] == [
        "reference_unit_missing_expected_script"
    ]


def test_quality_gate_flags_unbracketed_chapter_verse_missing_arabic():
    gate = ChunkQualityGate(ExpectedContentProfile(expected_scripts=frozenset({"arabic"})))

    warnings = gate.warnings_for("1:1 English translation only.")

    assert [warning["code"] for warning in warnings] == [
        "reference_unit_missing_expected_script"
    ]


def test_quality_gate_flags_quran_prefixed_chapter_verse_missing_arabic():
    gate = ChunkQualityGate(ExpectedContentProfile(expected_scripts=frozenset({"arabic"})))

    warnings = gate.warnings_for("Quran 1:1 English translation only.")

    assert [warning["code"] for warning in warnings] == [
        "reference_unit_missing_expected_script"
    ]


def test_quality_gate_accepts_mixed_arabic_reference_unit():
    gate = ChunkQualityGate(ExpectedContentProfile(expected_scripts=frozenset({"arabic"})))

    arabic_text = "\u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647"

    assert gate.warnings_for(f"[1:1]\n\n{arabic_text}\n\nAll praise is due to Allah.") == []


def test_quality_gate_flags_reference_unit_missing_expected_latin_script():
    gate = ChunkQualityGate(ExpectedContentProfile(expected_scripts=frozenset({"latin"})))

    arabic_text = "\u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647"
    warnings = gate.warnings_for(f"[1:1]\n\n{arabic_text}")

    assert warnings == [
        {
            "code": "reference_unit_missing_expected_script",
            "message": (
                "Reference-bearing chunk is expected to contain Latin script, "
                "but no Latin letters were detected."
            ),
            "expected_script": "latin",
        }
    ]


def test_quality_gate_accepts_latin_reference_unit():
    gate = ChunkQualityGate(ExpectedContentProfile(expected_scripts=frozenset({"latin"})))

    assert gate.warnings_for("[1:1]\n\nEnglish translation.") == []


def test_quality_gate_ignores_non_reference_english_chunk():
    gate = ChunkQualityGate(ExpectedContentProfile(expected_scripts=frozenset({"arabic"})))

    assert gate.warnings_for("English introduction without a structured reference.") == []
