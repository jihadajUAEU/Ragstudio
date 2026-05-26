from ragstudio.services.reference_regex_registry import (
    ARABIC_DIACRITICS_PATTERN,
    ARABIC_TOKEN_PATTERN,
    QUERY_GRAPH_CONTEXT_PATTERN,
    QUERY_NORMALIZED_PHRASE_PATTERN,
    QUERY_PHRASE_PATTERN,
    SCRIPT_PATTERNS,
)


def test_script_patterns_preserve_existing_script_detection() -> None:
    assert SCRIPT_PATTERNS["arabic"].search("\u0627\u0644\u0633\u0644\u0627\u0645")
    assert SCRIPT_PATTERNS["latin"].search("Evidence")
    assert SCRIPT_PATTERNS["hebrew"].search("\u05e9\u05dc\u05d5\u05dd")
    assert SCRIPT_PATTERNS["han"].search("\u6f22\u5b57")


def test_arabic_patterns_preserve_token_and_diacritic_behavior() -> None:
    assert ARABIC_TOKEN_PATTERN.findall("abc \u0627\u0644\u0633\u0644\u0627\u0645 123") == [
        "\u0627\u0644\u0633\u0644\u0627\u0645"
    ]
    assert ARABIC_DIACRITICS_PATTERN.sub("", "\u0642\u064f\u0631\u0652\u0622\u0646") == (
        "\u0642\u0631\u0622\u0646"
    )


def test_query_utility_patterns_preserve_non_reference_behavior() -> None:
    assert QUERY_GRAPH_CONTEXT_PATTERN.search("show nearby context")
    phrase = QUERY_PHRASE_PATTERN.search("which says guide us")
    assert phrase is not None
    assert phrase.group("phrase") == "guide us"
    assert QUERY_NORMALIZED_PHRASE_PATTERN.sub(" ", "guide-us").strip() == "guide us"
