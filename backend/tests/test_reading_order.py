from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.parser_normalization import NormalizedBlock


def block(text: str, bbox: list[int]) -> NormalizedBlock:
    return NormalizedBlock(
        text=text,
        page=1,
        block_type="text",
        source_item={"bbox": bbox},
    )


def test_canonical_block_order_groups_ltr_columns_between_full_width_blocks():
    blocks = [
        block("Title", [0, 0, 1000, 80]),
        block("Left 1", [40, 120, 430, 180]),
        block("Right 1", [560, 120, 950, 180]),
        block("Left 2", [40, 210, 430, 270]),
        block("Right 2", [560, 210, 950, 270]),
        block("Footer", [0, 790, 1000, 850]),
    ]

    ordered = ChunkSplitter()._canonical_block_order(
        blocks,
        domain_metadata=DomainMetadata(language="english", script="latin"),
    )

    assert [item.text for _, item in ordered] == [
        "Title",
        "Left 1",
        "Left 2",
        "Right 1",
        "Right 2",
        "Footer",
    ]


def test_canonical_block_order_uses_rtl_columns_for_arabic_documents():
    blocks = [
        block("\u0627\u0644\u0639\u0646\u0648\u0627\u0646", [0, 0, 1000, 80]),
        block("Left translation 1", [40, 120, 430, 180]),
        block("Arabic right 1", [560, 120, 950, 180]),
        block("Left translation 2", [40, 210, 430, 270]),
        block("Arabic right 2", [560, 210, 950, 270]),
    ]

    ordered = ChunkSplitter()._canonical_block_order(
        blocks,
        domain_metadata=DomainMetadata(language="arabic", script="arabic"),
    )

    assert [item.text for _, item in ordered] == [
        "\u0627\u0644\u0639\u0646\u0648\u0627\u0646",
        "Arabic right 1",
        "Arabic right 2",
        "Left translation 1",
        "Left translation 2",
    ]
