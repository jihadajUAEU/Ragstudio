from ragstudio.services.domain_retrieval_adapters import (
    RetrievalScoringSignals,
    scoring_signals_for_metadata,
)


def test_generic_metadata_has_no_hadith_count_boost():
    signals = scoring_signals_for_metadata({"domain_metadata": {"domain": "generic"}})

    assert signals == RetrievalScoringSignals()


def test_hadith_adapter_declares_count_answer_terms():
    signals = scoring_signals_for_metadata(
        {"domain_metadata": {"domain": "hadith", "collection": "sahih_bukhari"}}
    )

    assert signals.count_answer_terms == frozenset({"hadith", "collection", "bukhari"})
    assert signals.exact_script_boost == "arabic"
    assert signals.reference_label == "hadith"


def test_declared_arabic_script_enables_exact_script_boost_without_count_terms():
    signals = scoring_signals_for_metadata(
        {"domain_metadata": {"domain": "reference_heavy", "declared_scripts": ["arabic"]}}
    )

    assert signals.count_answer_terms == frozenset()
    assert signals.exact_script_boost == "arabic"
    assert signals.reference_label is None


def test_domain_metadata_script_field_enables_exact_script_boost():
    signals = scoring_signals_for_metadata(
        {"domain_metadata": {"domain": "reference_heavy", "script": "arabic"}}
    )

    assert signals.exact_script_boost == "arabic"
