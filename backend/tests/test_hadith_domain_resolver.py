from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.canonical_assembly import EvidenceBlockView, EvidenceSourceRef
from ragstudio.services.domain_resolvers.base import ResolverContext
from ragstudio.services.domain_resolvers.hadith import HadithResolver
from ragstudio.services.evidence_graph import EvidenceGraph

ARABIC_BODY = (
    "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647 "
    "\u0635\u0644\u0649 \u0627\u0644\u0644\u0647 \u0639\u0644\u064a\u0647 "
    "\u0648\u0633\u0644\u0645"
)


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


def context(domain: str = "hadith") -> ResolverContext:
    return ResolverContext(
        domain_metadata=DomainMetadata(domain=domain, document_type="collection"),
        parent_metadata={"parser_metadata": {"parser": "mineru"}},
        parent_source_location={"artifact": "source.md"},
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )


def test_hadith_resolver_attaches_body_that_unambiguously_precedes_late_header():
    blocks = [
        block(
            ARABIC_BODY,
            0,
            scripts={"arabic"},
        ),
        block("It was narrated that Anas said...", 1, scripts={"latin"}),
        block("Book 2, Hadith 29 - Grade: Sahih", 2, block_type="header"),
    ]

    units = HadithResolver().resolve_units(
        EvidenceGraph.from_blocks(blocks),
        context=context(),
    )

    assert len(units) == 1
    unit = units[0]
    assert unit.preview_ref == "book:2:hadith:29"
    assert "Book 2, Hadith 29" in unit.text
    assert "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647" in unit.text
    assert "It was narrated" in unit.text
    assert unit.metadata["canonical_reference_unit"]["answerable"] is True
    assert unit.metadata["reference_metadata"]["references"] == ["book:2:hadith:29"]
    assert unit.decisions[0].code == "late_header_body_reassociated"


def test_hadith_resolver_retains_translation_unit_when_required_arabic_evidence_is_absent():
    blocks = [
        block("It was narrated that Abu Umamah said...", 0, scripts={"latin"}),
        block("Book 36, Hadith 152 - Grade: Da'if", 1, block_type="header"),
    ]

    units = HadithResolver().resolve_units(
        EvidenceGraph.from_blocks(blocks),
        context=context(),
    )

    assert len(units) == 1
    assert units[0].preview_ref == "book:36:hadith:152"
    assert units[0].metadata["canonical_reference_unit"]["answerable"] is True
    assert units[0].metadata["canonical_reference_unit"]["body_status"] == "single_block"
    assert units[0].decisions[0].code == "reference_anchor_retained_missing_required_script"


def test_hadith_resolver_retains_ambiguous_headers_without_stealing_body():
    blocks = [
        block(
            ARABIC_BODY,
            0,
            scripts={"arabic"},
        ),
        block("It was narrated that Anas said...", 1, scripts={"latin"}),
        block("Book 2, Hadith 30", 2),
        block("Book 2, Hadith 29 - Grade: Sahih", 3, block_type="header"),
    ]

    units = HadithResolver().resolve_units(
        EvidenceGraph.from_blocks(blocks),
        context=context(),
    )

    by_ref = {unit.preview_ref: unit for unit in units}
    assert by_ref["book:2:hadith:30"].metadata["canonical_reference_unit"]["answerable"] is False
    assert by_ref["book:2:hadith:29"].metadata["canonical_reference_unit"]["answerable"] is False
    assert "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644" not in by_ref["book:2:hadith:29"].text


def test_hadith_resolver_keeps_partial_success_from_dropping_later_header():
    blocks = [
        block(
            "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647",
            0,
            scripts={"arabic"},
        ),
        block("It was narrated that Anas said...", 1, scripts={"latin"}),
        block("Book 2, Hadith 29 - Grade: Sahih", 2, block_type="header"),
        block("Book 2, Hadith 30 - Grade: Sahih", 3, block_type="header"),
    ]

    units = HadithResolver().resolve_units(
        EvidenceGraph.from_blocks(blocks),
        context=context(),
    )

    by_ref = {unit.preview_ref: unit for unit in units}
    assert by_ref["book:2:hadith:29"].metadata["canonical_reference_unit"]["answerable"] is True
    assert by_ref["book:2:hadith:30"].metadata["canonical_reference_unit"]["answerable"] is False
    assert (
        by_ref["book:2:hadith:30"].metadata["canonical_reference_unit"]["body_status"]
        == "header_only"
    )


def test_hadith_resolver_ignores_inline_cross_reference_as_anchor_boundary():
    blocks = [
        block("Book 3, Hadith 9", 0, block_type="header"),
        block(
            "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647",
            1,
            scripts={"arabic"},
        ),
        block("See Book 3, Hadith 10 for related context.", 2, scripts={"latin"}),
        block("The English translation continues after the inline citation.", 3, scripts={"latin"}),
    ]

    units = HadithResolver().resolve_units(
        EvidenceGraph.from_blocks(blocks),
        context=context(),
    )

    assert len(units) == 1
    assert units[0].preview_ref == "book:3:hadith:9"
    assert "inline citation" in units[0].text


def test_hadith_resolver_reverse_window_is_not_limited_to_three_blocks():
    blocks = [
        block(
            "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647",
            0,
            scripts={"arabic"},
        ),
        block("First translation line.", 1, scripts={"latin"}),
        block("Second translation line.", 2, scripts={"latin"}),
        block("Third translation line.", 3, scripts={"latin"}),
        block("Fourth translation line.", 4, scripts={"latin"}),
        block("Book 4, Hadith 7", 5, block_type="header"),
    ]

    units = HadithResolver().resolve_units(
        EvidenceGraph.from_blocks(blocks),
        context=context(),
    )

    assert len(units) == 1
    assert units[0].preview_ref == "book:4:hadith:7"
    assert "Fourth translation line." in units[0].text
    assert "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644" in units[0].text


def test_hadith_resolver_ignores_non_hadith_domains():
    blocks = [
        block(
            ARABIC_BODY,
            0,
            scripts={"arabic"},
        ),
        block("Book 2, Hadith 29 - Grade: Sahih", 1, block_type="header"),
    ]

    units = HadithResolver().resolve_units(
        EvidenceGraph.from_blocks(blocks),
        context=context(domain="quran"),
    )

    assert units == []
