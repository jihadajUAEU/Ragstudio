from ragstudio.services.arabic_text import (
    arabic_query_variants,
    arabic_tokens,
    normalize_arabic_text,
)


def test_normalize_removes_diacritics_and_tatweel():
    assert normalize_arabic_text("وَحَنَانًا مِّن لَّدُنَّا") == "وحنانا من لدنا"


def test_normalize_unifies_alef_and_ya_variants():
    assert normalize_arabic_text("إِنَّ ٱلْهُدَىٰ") == "ان الهدي"


def test_tokens_include_prefix_stripped_waw_variant():
    tokens = arabic_tokens("وَحَنَانًا مِّن لَّدُنَّا")

    assert "وحنانا" in tokens
    assert "حنانا" in tokens
    assert "لدنا" in tokens


def test_query_variants_include_original_normalized_and_prefix_stripped():
    assert arabic_query_variants("وحنانا") == ["وحنانا", "حنانا"]
