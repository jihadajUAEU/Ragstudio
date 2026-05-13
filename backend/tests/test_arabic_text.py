from ragstudio.services.arabic_text import (
    arabic_query_variants,
    arabic_tokens,
    normalize_arabic_text,
)


def test_normalize_removes_diacritics_and_tatweel():
    assert normalize_arabic_text("وَحَنَانًا مِّن لَّدُنَّا") == "وحنانا من لدنا"


def test_normalize_unifies_alef_and_ya_variants():
    assert normalize_arabic_text("إِنَّ ٱلْهُدَىٰ") == "ان الهدي"


def test_normalize_converts_arabic_presentation_forms_from_pdf_text_layer():
    text = "ﻭﭐﺗﻞ ﻣﺎ ﺃﻭﺣﻰ ﺇﻟﻴﻚ"

    assert normalize_arabic_text(text) == "واتل ما اوحي اليك"
    assert arabic_tokens(text) == ["واتل", "اتل", "ما", "اوحي", "اليك"]


def test_tokens_include_prefix_stripped_waw_variant():
    tokens = arabic_tokens("وَحَنَانًا مِّن لَّدُنَّا")

    assert "وحنانا" in tokens
    assert "حنانا" in tokens
    assert "لدنا" in tokens


def test_query_variants_include_original_normalized_and_prefix_stripped():
    assert arabic_query_variants("وحنانا") == ["وحنانا", "حنانا"]
