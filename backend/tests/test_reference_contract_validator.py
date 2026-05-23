from ragstudio.services.page_sampler import SampledPage
from ragstudio.services.reference_contract_validator import (
    ReferenceContractCandidate,
    ReferenceContractValidator,
)


def test_validator_rejects_chapter_verse_when_clearquran_uses_local_verse_numbers():
    pages = [
        SampledPage(
            page_number=168,
            text=(
                "Surah 7\nThe Elevations\n"
                '104 Moses said, "O Pharaoh, I am a messenger from the Lord of the Worlds."\n'
                "105 It is only proper that I should not say about Allah anything other than truth."
            ),
            image_data_url="data:image/png;base64,page168",
        )
    ]
    candidate = ReferenceContractCandidate(
        source="test_nonmatching",
        schema_type="chapter_verse",
        primary_anchor_regex=(
            r"(\bVerse\s+|\[)(?P<chapter>\d{1,4})\s*:\s*"
            r"(?P<verse>\d{1,4})\]?"
        ),
        inline_reference_regex=r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
        unit="verse",
        required_groups=frozenset({"chapter", "verse"}),
        canonical_ref_template="{chapter}:{verse}",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].matched_units == 0
    assert result.candidates[0].required_groups_present is True


def test_validator_selects_composite_surah_context_and_local_verse_candidate():
    pages = [
        SampledPage(
            page_number=168,
            text=(
                "Surah 7\nThe Elevations\n"
                '104 Moses said, "O Pharaoh, I am a messenger from the Lord of the Worlds."\n'
                "105 It is only proper that I should not say about Allah anything other than truth."
            ),
            image_data_url="data:image/png;base64,page168",
        )
    ]
    candidate = ReferenceContractCandidate(
        source="ai_observed",
        schema_type="chapter_verse",
        context_anchor_regex=r"\bSurah\s+(?P<chapter>\d{1,4})\b",
        unit_anchor_regex=r"\b(?P<verse>10[45])\b",
        unit="verse",
        context_required_groups=frozenset({"chapter"}),
        unit_required_groups=frozenset({"verse"}),
        canonical_ref_template="{chapter}:{verse}",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "verified"
    assert result.selected is not None
    assert result.selected.source == "ai_observed"
    assert result.selected.strategy == "contextual_unit"
    assert result.selected.matched_units == 2
    assert result.selected.examples[0]["reference"] == "7:104"


def test_validator_selects_matching_bracketed_quran_candidate():
    pages = [
        SampledPage(
            page_number=2,
            text="[1:1] Arabic verse text All praise is due to Allah\n[1:2] Arabic verse text",
            image_data_url=None,
        )
    ]
    candidate = ReferenceContractCandidate(
        source="ai_observed",
        schema_type="chapter_verse",
        primary_anchor_regex=r"\[(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\]",
        inline_reference_regex=r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
        unit="verse",
        required_groups=frozenset({"chapter", "verse"}),
        canonical_ref_template="{chapter}:{verse}",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "verified"
    assert result.selected is not None
    assert result.selected.source == "ai_observed"
    assert result.selected.matched_units == 2
    assert result.selected.examples[0]["reference"] == "1:1"
    assert result.selected.examples[0]["raw"] == "[1:1]"


def test_validator_rejects_schema_unsafe_regex_even_when_it_matches():
    pages = [
        SampledPage(
            page_number=2,
            text="Verse [1:1] Arabic verse text\n[1:2] Arabic verse text",
            image_data_url=None,
        )
    ]
    candidate = ReferenceContractCandidate(
        source="ai_observed",
        schema_type="chapter_verse",
        primary_anchor_regex=(
            r"(?:Verse\s+)?\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]"
        ),
        unit="verse",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].valid_regex is False
    assert result.candidates[0].rejection_reason is not None
    assert result.candidates[0].rejection_reason.startswith("unsupported_regex:")


def test_validator_accepts_custom_single_anchor_contract():
    pages = [
        SampledPage(
            page_number=1,
            text="Article 12.7 The procedure starts here.",
            image_data_url=None,
        )
    ]
    candidate = ReferenceContractCandidate(
        source="ai_observed",
        schema_type="article_clause",
        primary_anchor_regex=r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)",
        required_groups=frozenset({"article", "clause"}),
        canonical_ref_template="article:{article}:clause:{clause}",
        unit="article_clause",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "verified"
    assert result.selected is not None
    assert result.selected.schema_type == "article_clause"
    assert result.selected.required_groups_present is True
    assert result.selected.matched_units == 1
    assert result.selected.examples[0]["reference"] == "article:12:clause:7"


def test_validator_rejects_nonmatching_custom_single_anchor_contract():
    pages = [
        SampledPage(
            page_number=1,
            text="Section 12.7 The procedure starts here.",
            image_data_url=None,
        )
    ]
    candidate = ReferenceContractCandidate(
        source="ai_observed",
        schema_type="article_clause",
        primary_anchor_regex=r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)",
        required_groups=frozenset({"article", "clause"}),
        canonical_ref_template="article:{article}:clause:{clause}",
        unit="article_clause",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].valid_regex is True
    assert result.candidates[0].required_groups_present is True
    assert result.candidates[0].matched_units == 0
    assert result.candidates[0].rejection_reason == "no_sample_matches"


def test_validator_rejects_contextual_candidate_missing_declared_required_field():
    pages = [
        SampledPage(
            page_number=1,
            text="Article 12\nClause 7 The procedure starts here.",
            image_data_url=None,
        )
    ]
    candidate = ReferenceContractCandidate(
        source="ai_observed",
        schema_type="article_clause_item",
        context_anchor_regex=r"Article\s+(?P<article>\d+)",
        unit_anchor_regex=r"Clause\s+(?P<clause>\d+)",
        required_groups=frozenset({"article", "clause", "item"}),
        context_required_groups=frozenset({"article"}),
        unit_required_groups=frozenset({"clause"}),
        canonical_ref_template="article:{article}:clause:{clause}:item:{item}",
        unit="clause",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].required_groups_present is False
    assert result.candidates[0].matched_units == 0
    assert result.candidates[0].examples == []
    assert result.candidates[0].rejection_reason == "no_sample_matches"


def test_validator_rejects_single_anchor_empty_required_capture():
    pages = [
        SampledPage(
            page_number=1,
            text="Article 12.",
            image_data_url=None,
        )
    ]
    candidate = ReferenceContractCandidate(
        source="ai_observed",
        schema_type="article_clause",
        primary_anchor_regex=r"Article\s+(?P<article>\d+)\.(?P<clause>\d*)",
        required_groups=frozenset({"article", "clause"}),
        canonical_ref_template="article:{article}:clause:{clause}",
        unit="article_clause",
    )

    result = ReferenceContractValidator().validate(pages, [candidate])

    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].required_groups_present is True
    assert result.candidates[0].matched_units == 0
    assert result.candidates[0].examples == []
    assert result.candidates[0].rejection_reason == "no_sample_matches"
