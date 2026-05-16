from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
from ragstudio.services.lexical_language_adapters import (
    ArabicLexicalAdapter,
    GenericLatinAdapter,
)


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
    assert expansion.terms == ["حنان", "حنانا", "وحنانا"]
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

    assert next_expansion.terms == ["حنان", "حنانا", "وحنانا"]


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
    }


def research_domain_metadata() -> dict[str, object]:
    return {
        "domain": "research",
        "document_type": "paper",
        "language": "english",
        "tags": ["research", "paper"],
    }


def test_domain_query_expansion_prefers_arabic_for_quran_transliteration():
    service = DomainQueryExpansionService()

    result = service.expand("hanan", domain_metadata=[quran_domain_metadata()])

    assert result.original_query == "hanan"
    assert result.domain_family == "arabic_religious"
    assert result.expansions[0].terms == ["حنان", "حنانا", "وحنانا"]
    assert result.retrieval_passes[0].name == "lexical_expanded_token"
    assert result.retrieval_passes[0].query == "حنان"
    assert result.retrieval_passes[0].direct_evidence is True
    assert result.trace["expanded_terms"] == ["حنان", "حنانا", "وحنانا"]


def test_domain_query_expansion_does_not_cross_script_expand_research_text():
    service = DomainQueryExpansionService()

    result = service.expand("hanan", domain_metadata=[research_domain_metadata()])

    assert result.domain_family == "generic"
    assert result.expansions == []
    assert result.retrieval_passes == []
    assert result.trace["expanded_terms"] == []
