import pytest
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.index_quality_gate import (
    IndexQualityGate,
    IndexQualityGateError,
)


def _chunk(text):
    return AdapterChunk(
        text=text,
        source_location={"page": 1},
        metadata={
            "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
            "extraction_quality": {"status": "passed"},
        },
    )


def test_gate_rejects_raw_pdf_chunks():
    with pytest.raises(IndexQualityGateError, match="raw_pdf_persisted"):
        IndexQualityGate().validate_adapter_chunks([_chunk("%PDF-1.4\n1 0 obj")], language="arabic")


def test_gate_rejects_arabic_document_without_arabic_tokens():
    with pytest.raises(IndexQualityGateError, match="arabic_tokens_missing"):
        IndexQualityGate().validate_adapter_chunks(
            [_chunk("English only text from a parser")],
            language="arabic",
        )


def test_gate_accepts_arabic_mineru_chunks():
    report = IndexQualityGate().validate_adapter_chunks(
        [_chunk("وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً")],
        language="arabic",
    )

    assert report["status"] == "passed"
    assert report["arabic_token_count"] >= 3


def test_gate_annotates_metadata_aware_reference_warnings():
    chunks = [
        AdapterChunk(
            text="And affection from Us and purity, and he was fearing of Allah.",
            source_location={"page": 312},
            metadata={
                "reference_metadata": {"references": ["19:13"]},
                "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
            },
        ),
        _chunk("[1:1]\n\n\u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647"),
    ]

    report = IndexQualityGate().validate_adapter_chunks(
        chunks,
        language="quran",
        domain_metadata=DomainMetadata(
            domain="quran_tafseer",
            language="arabic",
            tags=["quran", "arabic"],
            citation_style="surah_ayah",
            script="arabic",
        ),
    )

    assert report["status"] == "passed_with_warnings"
    assert report["parser_quality"] == {
        "warning_counts": {"reference_unit_missing_expected_script": 1},
        "affected_chunks": 1,
    }
    assert chunks[0].metadata["extraction_quality"]["parser_warnings"][0][
        "expected_script"
    ] == "arabic"
