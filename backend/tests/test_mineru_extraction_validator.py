import pytest
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.mineru_extraction_validator import (
    MinerUExtractionContractError,
    MinerUExtractionValidator,
)


def _chunk(
    text: str,
    metadata: dict | None = None,
    source_location: dict | None = None,
) -> AdapterChunk:
    return AdapterChunk(
        text=text,
        source_location=source_location or {"page": 1},
        metadata=metadata
        or {"parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"}},
    )


def test_rejects_raw_pdf_syntax():
    chunks = [_chunk("%PDF-1.7\n1 0 obj << /Type /Page >>\nendobj")]

    with pytest.raises(MinerUExtractionContractError, match="raw_pdf_syntax"):
        MinerUExtractionValidator().validate(chunks, expected_language="arabic")


def test_rejects_empty_extraction():
    with pytest.raises(MinerUExtractionContractError, match="empty_extraction"):
        MinerUExtractionValidator().validate([], expected_language="arabic")


def test_rejects_missing_arabic_when_expected():
    chunks = [_chunk("This is extracted English text.")]

    with pytest.raises(MinerUExtractionContractError, match="arabic_text_missing"):
        MinerUExtractionValidator().validate(chunks, expected_language="arabic")


def test_rejects_non_mineru_backend():
    chunks = [_chunk("وحنانا من لدنا", {"parser_metadata": {"backend": "fallback"}})]

    with pytest.raises(MinerUExtractionContractError, match="non_mineru_backend"):
        MinerUExtractionValidator().validate(chunks, expected_language="arabic")


def test_rejects_insufficient_page_coverage():
    chunks = [
        _chunk(
            "وحنانا من لدنا وزكاة وكان تقيا",
            {"parser_metadata": {"backend": "mineru", "total_pages": 10}},
            {"page": 1},
        )
    ]

    with pytest.raises(MinerUExtractionContractError, match="insufficient_page_coverage"):
        MinerUExtractionValidator().validate(chunks, expected_language="arabic")


def test_accepts_valid_mineru_arabic_extraction():
    chunks = [
        _chunk(
            "وحنانا من لدنا وزكاة وكان تقيا",
            {"parser_metadata": {"backend": "mineru", "total_pages": 2}},
            {"page": 1},
        ),
        _chunk(
            "وسلام عليه يوم ولد ويوم يموت",
            {"parser_metadata": {"backend": "mineru", "total_pages": 2}},
            {"page": 2},
        ),
    ]

    report = MinerUExtractionValidator().validate(chunks, expected_language="arabic")

    assert report.chunk_count == 2
    assert report.page_count == 2
    assert report.total_pages == 2
    assert report.arabic_character_count > 0
    assert report.parser_backend == "mineru"
