from ragstudio.services.reference_regex_registry import (
    ARABIC_DIACRITICS_PATTERN,
    ARABIC_TOKEN_PATTERN,
    LEGAL_SECTION_PATTERN,
    QUERY_REFERENCE_PATTERN,
    REFERENCE_PATTERN,
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


def test_reference_patterns_preserve_quran_reference_behavior() -> None:
    match = REFERENCE_PATTERN.search("See 12:13 for the reference")
    assert match is not None
    assert match.group("chapter") == "12"
    assert match.group("verse") == "13"

    verifier_match = QUERY_REFERENCE_PATTERN.search("[12:13]")
    assert verifier_match is not None
    assert verifier_match.group("reference") == "12:13"


def test_legal_section_pattern_preserves_section_symbol_behavior() -> None:
    match = LEGAL_SECTION_PATTERN.search("See § 12.3 for details")

    assert match is not None
    assert match.group("section") == "12.3"
