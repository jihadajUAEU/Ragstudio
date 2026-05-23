from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_metadata_ai_suggester import DomainMetadataAiSuggester
from ragstudio.services.page_sampler import SampledPage
from ragstudio.services.reference_contracts import build_executable_reference_contract
from ragstudio.services.reference_contract_validator import ReferenceContractValidator


def test_reference_contract_candidates_include_declared_groups_and_template():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "fields": {"folio": "folio_number", "line": "line_number"},
                "canonical_ref_template": "folio:{folio}:line:{line}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
                    "unit": "folio_line",
                },
                "context_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)",
                    "unit": "folio",
                },
                "unit_anchor": {
                    "regex": r"Line\s+(?P<line>\d+)",
                    "unit": "line",
                },
            },
        }
    )

    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )

    single_anchor = next(candidate for candidate in candidates if candidate.primary_anchor_regex)
    contextual = next(candidate for candidate in candidates if candidate.context_anchor_regex)
    assert single_anchor.required_groups == frozenset({"folio", "line"})
    assert single_anchor.canonical_ref_template == "folio:{folio}:line:{line}"
    assert contextual.required_groups == frozenset({"folio", "line"})
    assert contextual.context_required_groups == frozenset({"folio"})
    assert contextual.unit_required_groups == frozenset({"line"})
    assert contextual.canonical_ref_template == "folio:{folio}:line:{line}"


def test_quran_like_candidate_uses_template_identity_not_page_field():
    custom_json = {
        "reference_schema": {
            "type": "quran_tafseer",
            "fields": {
                "chapter": "chapter_number",
                "verse": "verse_number",
                "page": "page_number",
            },
            "canonical_ref_template": "{chapter}:{verse}",
        },
        "domain_structure": {
            "primary_anchor": {
                "regex": r"\[(?P<chapter>\d+):(?P<verse>\d+)\]",
                "unit": "verse",
                "verified": True,
            },
        },
    }
    metadata = DomainMetadata(custom_json=custom_json)
    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )
    validation = ReferenceContractValidator().validate(
        [SampledPage(page_number=1, text="[1:1] [1:2]")],
        candidates,
    )
    contract = build_executable_reference_contract(custom_json)

    assert contract.required_groups == frozenset({"chapter", "verse"})
    assert contract.verified is True
    assert candidates[0].required_groups == frozenset({"chapter", "verse"})
    assert validation.status == "verified"
    assert validation.selected is not None
    assert validation.selected.required_groups_present is True
    assert validation.selected.matched_units == 2
    assert [example["reference"] for example in validation.selected.examples] == [
        "1:1",
        "1:2",
    ]


def test_production_candidate_rejects_empty_required_capture():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "article_clause",
                "fields": {"article": "article_number", "clause": "clause_number"},
                "canonical_ref_template": "article:{article}:clause:{clause}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Article\s+(?P<article>\d+)\.(?P<clause>\d*)",
                    "unit": "article_clause",
                }
            },
        }
    )
    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )

    result = ReferenceContractValidator().validate(
        [
            SampledPage(
                page_number=1,
                text="Article 12. The procedure starts here.",
            )
        ],
        candidates,
    )

    assert candidates[0].required_groups == frozenset({"article", "clause"})
    assert candidates[0].canonical_ref_template == "article:{article}:clause:{clause}"
    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].required_groups_present is True
    assert result.candidates[0].matched_units == 0
    assert result.candidates[0].examples == []


def test_contextual_production_candidate_missing_declared_field_does_not_verify():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "article_clause_item",
                "fields": {
                    "article": "article_number",
                    "clause": "clause_number",
                    "item": "item_number",
                },
                "canonical_ref_template": "article:{article}:clause:{clause}:item:{item}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": r"Article\s+(?P<article>\d+)",
                    "unit": "article",
                },
                "unit_anchor": {
                    "regex": r"Clause\s+(?P<clause>\d+)",
                    "unit": "clause",
                },
            },
        }
    )
    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )

    result = ReferenceContractValidator().validate(
        [
            SampledPage(
                page_number=1,
                text="Article 12\nClause 7 The procedure starts here.",
            )
        ],
        candidates,
    )

    assert candidates[0].required_groups == frozenset({"article", "clause", "item"})
    assert candidates[0].context_required_groups == frozenset({"article"})
    assert candidates[0].unit_required_groups == frozenset({"clause"})
    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].required_groups_present is False
    assert result.candidates[0].matched_units == 0


def test_contextual_contract_validation_uses_generic_declared_context_unit():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "fields": {"folio": "folio_number", "line": "line_number"},
                "canonical_ref_template": "folio:{folio}:line:{line}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)",
                },
                "unit_anchor": {
                    "regex": r"Line\s+(?P<line>\d+)",
                    "unit": "line",
                },
            },
        }
    )
    suggester = DomainMetadataAiSuggester()
    candidates = suggester._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )
    validation = ReferenceContractValidator().validate(
        [
            SampledPage(
                page_number=1,
                text="Folio 12\nLine 7 The note starts here.",
            )
        ],
        candidates,
    )

    result = suggester._apply_reference_contract_validation(metadata, validation)

    domain_structure = result.custom_json["domain_structure"]
    context_anchor = domain_structure["context_anchor"]
    assert validation.status == "verified"
    assert context_anchor["verified"] is True
    assert context_anchor["unit"] == "folio"
    assert context_anchor["unit"] != "chapter"
