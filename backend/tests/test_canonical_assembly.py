from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.canonical_assembly import (
    EvidenceBoundingBox,
    EvidenceSourceRef,
    block_views_from_normalized,
)
from ragstudio.services.domain_resolvers.base import ResolverContext, resolver_key
from ragstudio.services.parser_normalization import NormalizationWarning, NormalizedBlock


def test_block_views_from_normalized_preserves_source_refs_warnings_and_scripts():
    normalized = [
        NormalizedBlock(
            text="Book 2, Hadith 29 - Grade: Sahih",
            page=127,
            block_type="header",
            source_item={"bbox": [10, 20, 300, 40]},
        ),
        NormalizedBlock(
            text=(
                "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647 "
                "\u0635\u0644\u0649 \u0627\u0644\u0644\u0647 \u0639\u0644\u064a\u0647 "
                "\u0648\u0633\u0644\u0645"
            ),
            page=127,
            block_type="text",
            source_item={"bbox": [10, 50, 300, 90]},
            warnings=(
                NormalizationWarning(
                    code="recovered_text_from_disallowed_block",
                    message="Recovered text.",
                    block_type="text",
                    page=127,
                ),
            ),
        ),
    ]

    blocks = block_views_from_normalized(
        normalized,
        content_list_ref="source_a86dd9bf/source/auto/source_content_list.json",
    )

    assert [block.block_type for block in blocks] == ["header", "text"]
    assert blocks[0].page_start == 127
    assert blocks[0].source_ref.block_index == 0
    assert blocks[0].bbox == EvidenceBoundingBox(x0=10.0, y0=20.0, x1=300.0, y1=40.0)
    assert blocks[1].scripts == frozenset({"arabic"})
    assert blocks[1].parser_warnings[0]["code"] == "recovered_text_from_disallowed_block"
    assert blocks[1].source_ref == EvidenceSourceRef(
        artifact_ref="source_a86dd9bf/source/auto/source_content_list.json",
        block_index=1,
    )


def test_resolver_key_uses_domain_and_document_type():
    context = ResolverContext(
        domain_metadata=DomainMetadata(domain="hadith", document_type="collection"),
        parent_metadata={},
        parent_source_location={},
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )

    assert resolver_key(context) == "hadith:collection"
