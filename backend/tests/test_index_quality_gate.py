import pytest
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
