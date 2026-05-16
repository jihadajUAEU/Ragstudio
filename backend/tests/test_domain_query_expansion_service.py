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


def test_generic_latin_adapter_does_not_invent_cross_script_terms():
    adapter = GenericLatinAdapter()

    expansion = adapter.expand_query("climate resilience")

    assert expansion.language == "unknown"
    assert expansion.script == "latin"
    assert expansion.normalized_query == "climate resilience"
    assert expansion.terms == ["climate resilience"]
    assert expansion.match_type == "normalized_text"
    assert expansion.confidence == 0.5
