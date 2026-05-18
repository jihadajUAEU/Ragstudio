import json

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.modal_preprocessor import (
    MODAL_ROUTER_PROCESSED_FLAG,
    ModalPreprocessor,
)


def test_modal_preprocessor_routes_content_list_once(tmp_path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "A text block.", "page_idx": 0},
                {
                    "type": "table",
                    "table_body": "| A | B |\n| 1 | 2 |",
                    "page_idx": 1,
                },
            ]
        ),
        encoding="utf-8",
    )
    parser_metadata = {
        "artifact_extract_dir": str(tmp_path),
        "content_list_ref": "source_content_list.json",
        "parser_mode": "mineru_strict",
    }
    chunk = AdapterChunk(
        text="ignored",
        source_location={"artifact": "source.pdf"},
        metadata={"parser_metadata": parser_metadata},
        runtime_source_id="runtime-source",
        preview_ref="preview/source.md",
    )

    chunks = ModalPreprocessor().preprocess(
        [chunk],
        domain_metadata=DomainMetadata(),
    )

    assert len(chunks) == 2
    assert all(item.metadata[MODAL_ROUTER_PROCESSED_FLAG] is True for item in chunks)
    assert chunks[1].metadata["modality"] == "table"
    assert chunks[1].metadata["parser_metadata"]["content_list_ref"] == (
        "source_content_list.json"
    )
    assert ModalPreprocessor().preprocess(
        chunks,
        domain_metadata=DomainMetadata(),
    ) == chunks


def test_modal_preprocessor_returns_original_chunks_when_no_content_list():
    chunk = AdapterChunk(
        text="original text",
        source_location={"artifact": "source.pdf"},
        metadata={"parser_metadata": {"parser_mode": "mineru_strict"}},
    )

    chunks = ModalPreprocessor().preprocess(
        [chunk],
        domain_metadata=DomainMetadata(),
    )

    assert chunks == [chunk]
