from ragstudio.services.domain_lexical_registry import DomainLexicalRegistry
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
from ragstudio.services.lexical_language_adapters import (
    ArabicLexicalAdapter,
    GenericLatinAdapter,
    LexicalExpansion,
)
from ragstudio.services.query_hypothesis_service import QueryHypothesis, QueryTargetTerm


class LegalLexicalAdapter:
    def supports_query(self, query: str) -> bool:
        return "force majeure" in query.casefold()

    def expand_query(self, query: str) -> LexicalExpansion:
        normalized_query = " ".join(query.strip().casefold().split())
        return LexicalExpansion(
            original_query=query,
            normalized_query=normalized_query,
            language="english",
            script="latin",
            match_type="domain_synonym",
            confidence=0.91,
            source="legal_test_adapter",
            terms=["force majeure", "act of god", "impossibility"],
        )


def test_domain_query_expansion_uses_registered_non_arabic_adapter():
    registry = DomainLexicalRegistry()
    registry.register("legal_reference", LegalLexicalAdapter())
    service = DomainQueryExpansionService(registry=registry)

    expansion = service.expand(
        "force majeure clause",
        domain_metadata=[
            {
                "domain": "legal",
                "document_type": "contract",
                "tags": ["contract", "reference"],
            }
        ],
    )

    assert expansion.domain_family == "legal_reference"
    assert [item.source for item in expansion.expansions] == ["legal_test_adapter"]
    assert expansion.trace["adapter_sources"] == ["legal_test_adapter"]
    assert "act of god" in expansion.trace["expanded_terms"]
    assert any(item.query == "impossibility" for item in expansion.retrieval_passes)


def test_domain_query_expansion_preserves_legal_adapter_with_reference_contract():
    service = DomainQueryExpansionService()

    expansion = service.expand(
        "force majeure contract section",
        domain_metadata=[
            {
                "domain": "legal",
                "document_type": "contract",
                "custom_json": {
                    "reference_schema": {
                        "type": "article_clause",
                        "fields": {
                            "article": "article_number",
                            "clause": "clause_number",
                        },
                    }
                },
            }
        ],
    )

    assert expansion.domain_family == "legal_reference"
    assert expansion.trace["adapter_sources"] == ["legal_keyword_adapter"]
    assert "article" in expansion.trace["expanded_terms"]
    assert any(item.query == "agreement" for item in expansion.retrieval_passes)


def test_domain_query_expansion_uses_reference_contract_family():
    service = DomainQueryExpansionService()

    expansion = service.expand(
        "quran 1:5",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "tags": ["quran", "arabic"],
                "custom_json": quran_domain_metadata()["custom_json"],
            }
        ],
    )

    assert expansion.domain_family == "reference_heavy"
    assert expansion.trace["domain_family"] == "reference_heavy"


def test_domain_query_expansion_does_not_use_arabic_adapter_without_script_contract():
    service = DomainQueryExpansionService()

    expansion = service.expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "archival_text",
                "document_type": "register",
                "custom_json": {
                    "reference_schema": {
                        "type": "folio_line",
                        "fields": {"folio": "folio_number", "line": "line_number"},
                    }
                },
            }
        ],
    )

    assert expansion.domain_family == "reference_heavy"
    assert expansion.expansions == []
    assert expansion.retrieval_passes == []
    assert expansion.trace["adapter_sources"] == []


def test_domain_query_expansion_does_not_treat_language_as_script_declaration():
    service = DomainQueryExpansionService()

    expansion = service.expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "archive",
                "language": "arabic",
                "custom_json": {
                    "reference_schema": {
                        "type": "folio_line",
                        "fields": {"folio": "folio_number", "line": "line_number"},
                    }
                },
            }
        ],
    )

    assert expansion.domain_family == "reference_heavy"
    assert expansion.expansions == []
    assert expansion.retrieval_passes == []
    assert expansion.trace["adapter_sources"] == []


def test_domain_query_expansion_legacy_arabic_adapter_does_not_duplicate_passes():
    service = DomainQueryExpansionService(arabic_adapter=ArabicLexicalAdapter())

    result = service.expand("hanan", domain_metadata=[quran_domain_metadata()])

    assert len(result.expansions) == 1
    assert len(result.retrieval_passes) == 2
    assert [item.query for item in result.retrieval_passes] == result.expansions[0].terms
    assert len({item.query for item in result.retrieval_passes}) == 2
    assert result.trace["adapter_sources"] == ["arabic_transliteration_lexicon"]


def test_arabic_adapter_preserves_existing_arabic_variants():
    adapter = ArabicLexicalAdapter()

    expansion = adapter.expand_query("وحنانا")

    assert expansion.language == "arabic"
    assert expansion.script == "arab"
    assert expansion.normalized_query == "وحنانا"
    assert expansion.terms == ["وحنانا", "حنانا"]
    assert expansion.match_type == "exact_script"
    assert expansion.confidence == 1.0


def test_arabic_adapter_expands_known_latin_transliteration():
    adapter = ArabicLexicalAdapter()

    expansion = adapter.expand_query("hanan")

    assert expansion.language == "arabic"
    assert expansion.script == "arab"
    assert expansion.normalized_query == "hanan"
    assert expansion.terms == ["حنانا", "وحنانا"]
    assert "حنان" not in expansion.terms
    assert expansion.match_type == "transliteration"
    assert expansion.confidence >= 0.9


def test_arabic_adapter_detects_presentation_form_arabic_as_exact_script():
    adapter = ArabicLexicalAdapter()

    expansion = adapter.expand_query("ﻭﭐﺗﻞ")

    assert adapter.supports_query("ﻭﭐﺗﻞ") is True
    assert expansion.language == "arabic"
    assert expansion.script == "arab"
    assert expansion.normalized_query == "واتل"
    assert expansion.terms == ["واتل", "اتل"]
    assert expansion.match_type == "exact_script"
    assert expansion.confidence == 1.0


def test_arabic_adapter_detects_extended_b_arabic_as_exact_script():
    adapter = ArabicLexicalAdapter()

    expansion = adapter.expand_query("\u0870")

    assert adapter.supports_query("\u0870") is True
    assert expansion.language == "arabic"
    assert expansion.script == "arab"
    assert expansion.terms
    assert expansion.match_type == "exact_script"
    assert expansion.confidence == 1.0


def test_arabic_transliteration_terms_are_not_shared_between_expansions():
    adapter = ArabicLexicalAdapter()

    expansion = adapter.expand_query("hanan")
    expansion.terms.append("leaked")

    next_expansion = adapter.expand_query("hanan")

    assert next_expansion.terms == ["حنانا", "وحنانا"]


def test_generic_latin_adapter_does_not_invent_cross_script_terms():
    adapter = GenericLatinAdapter()

    expansion = adapter.expand_query("climate resilience")

    assert expansion.language == "unknown"
    assert expansion.script == "latin"
    assert expansion.normalized_query == "climate resilience"
    assert expansion.terms == ["climate resilience"]
    assert expansion.match_type == "normalized_text"
    assert expansion.confidence == 0.5


def quran_domain_metadata() -> dict[str, object]:
    return {
        "domain": "quran_tafseer",
        "document_type": "commentary",
        "language": "mixed",
        "tags": ["quran", "tafseer", "arabic"],
        "script": "mixed",
        "custom_json": {
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter_number", "verse": "verse_number"},
            },
            "quality_policy": {
                "required_scripts_by_unit_role": {"verse": ["arabic"]},
            },
        },
    }


def research_domain_metadata() -> dict[str, object]:
    return {
        "domain": "research",
        "document_type": "paper",
        "language": "english",
        "tags": ["research", "paper"],
    }


def arabic_research_domain_metadata() -> dict[str, object]:
    return {
        "domain": "research",
        "document_type": "paper",
        "language": " Arabic ",
        "tags": ("arabic", "research"),
        "script": "mixed",
    }


def mixed_admin_domain_metadata() -> dict[str, object]:
    return {
        "domain": "admin",
        "document_type": "memo",
        "language": "mixed",
        "tags": {"arabic", "internal"},
        "script": " Mixed ",
    }


def test_domain_query_expansion_prefers_arabic_for_quran_transliteration():
    service = DomainQueryExpansionService()

    result = service.expand("hanan", domain_metadata=[quran_domain_metadata()])

    assert result.original_query == "hanan"
    assert result.domain_family == "reference_heavy"
    assert result.expansions[0].terms == ["حنانا", "وحنانا"]
    assert result.retrieval_passes[0].name == "lexical_expanded_token"
    assert result.retrieval_passes[0].query == "حنانا"
    assert result.retrieval_passes[0].direct_evidence is True
    assert [item.query for item in result.retrieval_passes] == ["حنانا", "وحنانا"]
    assert [item.match_type for item in result.retrieval_passes] == [
        "transliteration",
        "transliteration",
    ]
    assert all(
        retrieval_pass.name == "lexical_expanded_token"
        and retrieval_pass.direct_evidence is True
        for retrieval_pass in result.retrieval_passes
    )
    assert result.trace["expanded_terms"] == ["حنانا", "وحنانا"]


def test_domain_query_expansion_uses_hypothesis_target_terms_from_sentence():
    service = DomainQueryExpansionService()
    hypothesis = QueryHypothesis(
        original_query="in which surah the word hanan is mentioned",
        intent="find_word_occurrence",
        target_terms=[
            QueryTargetTerm(
                surface="hanan",
                script="latin",
                language_hint="arabic",
                term_type="transliteration",
            )
        ],
        domain_hint="quran",
        answer_shape="surah_and_verse",
        confidence=0.8,
        valid=True,
    )

    result = service.expand(
        "in which surah the word hanan is mentioned",
        domain_metadata=[quran_domain_metadata()],
        query_hypothesis=hypothesis,
    )

    assert result.original_query == "in which surah the word hanan is mentioned"
    assert result.trace["expansion_source"] == "query_hypothesis"
    assert result.trace["expansion_input_terms"] == ["hanan"]
    assert result.trace["expanded_terms"] == ["حنانا", "وحنانا"]
    assert [item.query for item in result.retrieval_passes] == ["حنانا", "وحنانا"]


def test_domain_query_expansion_prepends_possible_reference_hypotheses():
    service = DomainQueryExpansionService()
    hypothesis = QueryHypothesis(
        original_query="Which hadith says about offering sacrifice for eid?",
        intent="reference_lookup",
        target_terms=[
            QueryTargetTerm(surface="offering", script="latin"),
            QueryTargetTerm(surface="sacrifice", script="latin"),
            QueryTargetTerm(surface="eid", script="latin"),
        ],
        domain_hint="hadith",
        answer_shape="reference",
        possible_references=["book:13:hadith:25", "book:34:hadith:288"],
        confidence=0.8,
        valid=True,
    )

    result = service.expand(
        "Which hadith says about offering sacrifice for eid?",
        domain_metadata=[
            {
                "domain": "hadith",
                "document_type": "collection",
                "tags": ["hadith", "islamic_text"],
            }
        ],
        query_hypothesis=hypothesis,
    )

    assert [item.name for item in result.retrieval_passes[:2]] == [
        "reference_exact",
        "reference_exact",
    ]
    assert [item.query for item in result.retrieval_passes[:2]] == [
        "book:13:hadith:25",
        "book:34:hadith:288",
    ]
    assert all(item.direct_evidence is True for item in result.retrieval_passes[:2])
    assert result.trace["possible_references"] == [
        "book:13:hadith:25",
        "book:34:hadith:288",
    ]


def test_domain_query_expansion_preserves_exact_script_match_type_on_passes():
    service = DomainQueryExpansionService()

    result = service.expand("وحنانا", domain_metadata=[quran_domain_metadata()])

    assert result.expansions[0].match_type == "exact_script"
    assert [item.query for item in result.retrieval_passes] == ["وحنانا", "حنانا"]
    assert [item.match_type for item in result.retrieval_passes] == [
        "exact_script",
        "exact_script",
    ]


def test_domain_query_expansion_does_not_cross_script_expand_research_text():
    service = DomainQueryExpansionService()

    result = service.expand("hanan", domain_metadata=[research_domain_metadata()])

    assert result.domain_family == "research_semantic"
    assert result.expansions == []
    assert result.retrieval_passes == []
    assert result.trace["expanded_terms"] == []


def test_domain_query_expansion_keeps_arabic_research_and_admin_generic():
    service = DomainQueryExpansionService()

    research_result = service.expand("hanan", domain_metadata=[arabic_research_domain_metadata()])
    admin_result = service.expand("hanan", domain_metadata=[mixed_admin_domain_metadata()])

    assert research_result.domain_family == "research_semantic"
    assert research_result.expansions == []
    assert research_result.retrieval_passes == []
    assert admin_result.domain_family == "generic"
    assert admin_result.expansions == []
    assert admin_result.retrieval_passes == []


def test_domain_query_expansion_trace_terms_are_not_mutated_by_expansion_terms():
    service = DomainQueryExpansionService()

    result = service.expand("hanan", domain_metadata=[quran_domain_metadata()])
    result.expansions[0].terms.append("leaked")

    assert result.trace["expanded_terms"] == ["حنانا", "وحنانا"]
    assert result.trace["expansions"][0]["terms"] == ["حنانا", "وحنانا"]


def test_domain_query_expansion_uses_legal_keyword_adapter():
    expansion = DomainQueryExpansionService().expand(
        "breach of contract section 12",
        domain_metadata=[{"domain": "legal", "document_type": "contract"}],
    )

    assert expansion.domain_family == "legal_reference"
    assert "agreement" in expansion.trace["expanded_terms"]
    assert "article" in expansion.trace["expanded_terms"]
    assert any(pass_.name == "lexical_expanded_token" for pass_ in expansion.retrieval_passes)


def test_domain_query_expansion_uses_financial_keyword_adapter():
    expansion = DomainQueryExpansionService().expand(
        "invoice tax amount",
        domain_metadata=[{"domain": "finance", "document_type": "invoice"}],
    )

    assert expansion.domain_family == "financial_reference"
    assert "bill" in expansion.trace["expanded_terms"]
    assert "vat" in expansion.trace["expanded_terms"]
