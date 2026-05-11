from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.document_chunking_policy import DocumentChunkingPolicy


def _chunk(text, references=None, page=1, block_id="b1"):
    return AdapterChunk(
        text=text,
        source_location={"page": page, "block_id": block_id},
        metadata={
            "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
            "reference_metadata": {"references": references or []},
            "mineru": {"block_id": block_id},
        },
        runtime_source_id=f"source-{block_id}",
        content_type="text",
        preview_ref=f"preview-{block_id}",
    )


def test_reference_chunk_is_not_split_when_within_limit():
    text = "[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً وَكَانَ تَقِيًّا"

    chunks = DocumentChunkingPolicy(max_chars=80).split_mineru_chunks(
        [_chunk(text, references=["19:13"])],
        domain_metadata={"domain": "quran", "language": "arabic"},
    )

    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].metadata["reference_metadata"]["references"] == ["19:13"]
    assert chunks[0].source_location["page"] == 1
    assert chunks[0].preview_ref == "preview-b1"


def test_large_quran_block_splits_on_reference_boundaries():
    text = (
        "[19:12] يَا يَحْيَى خُذِ الْكِتَابَ بِقُوَّةٍ "
        "[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً وَكَانَ تَقِيًّا "
        "[19:14] وَبَرًّا بِوَالِدَيْهِ"
    )

    chunks = DocumentChunkingPolicy(max_chars=90).split_mineru_chunks(
        [_chunk(text, references=["19:12", "19:13", "19:14"])],
        domain_metadata={"domain": "quran", "language": "arabic"},
    )

    assert [chunk.metadata["reference_metadata"]["references"] for chunk in chunks] == [
        ["19:12"],
        ["19:13"],
        ["19:14"],
    ]
    assert "وَحَنَانًا" in chunks[1].text


def test_neighbor_context_is_limited_to_adjacent_reference_family():
    chunks = [
        _chunk("[19:12] يَا يَحْيَى خُذِ الْكِتَابَ بِقُوَّةٍ", ["19:12"], page=10, block_id="b12"),
        _chunk("[19:13] وَحَنَانًا مِّن لَّدُنَّا", ["19:13"], page=10, block_id="b13"),
        _chunk("[20:1] طه", ["20:1"], page=11, block_id="b20"),
    ]

    policy = DocumentChunkingPolicy(max_chars=120, neighbor_window=1)
    split = policy.split_mineru_chunks(chunks, domain_metadata={"domain": "quran"})
    neighbors = policy.neighbor_context(split, target_reference="19:13")

    assert [chunk.metadata["reference_metadata"]["references"][0] for chunk in neighbors] == [
        "19:12"
    ]
