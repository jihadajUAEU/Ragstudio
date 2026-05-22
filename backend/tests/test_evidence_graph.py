from ragstudio.services.canonical_assembly import EvidenceBlockView, EvidenceSourceRef
from ragstudio.services.evidence_graph import EvidenceGraph


def block(
    text: str,
    index: int,
    *,
    block_type: str = "text",
    scripts=frozenset(),
):
    return EvidenceBlockView(
        text=text,
        block_type=block_type,
        page_start=127,
        page_end=127,
        source_ref=EvidenceSourceRef("source_content_list.json", index),
        scripts=frozenset(scripts),
    )


def test_graph_can_find_prior_arabic_blocks_for_late_hadith_header():
    blocks = [
        block(
            (
                "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647 "
                "\u0635\u0644\u0649 \u0627\u0644\u0644\u0647 \u0639\u0644\u064a\u0647 "
                "\u0648\u0633\u0644\u0645"
            ),
            0,
            scripts={"arabic"},
        ),
        block("It was narrated that Anas said...", 1, scripts={"latin"}),
        block("Book 2, Hadith 30", 2),
        block("Book 2, Hadith 29 - Grade: Sahih", 3, block_type="header"),
    ]

    graph = EvidenceGraph.from_blocks(blocks)
    nearby = graph.neighborhood(blocks[3], before=3, after=0)

    assert [item.source_ref.block_index for item in nearby] == [0, 1, 2]
    assert graph.blocks_with_script("arabic") == [blocks[0]]
    assert graph.page_blocks(127) == blocks
