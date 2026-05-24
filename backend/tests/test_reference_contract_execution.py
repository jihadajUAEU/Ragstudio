from ragstudio.services.page_sampler import SampledPage
from ragstudio.services.reference_contract_execution import (
    ContractAcceptance,
    ContractExtractor,
    GeneratedReferenceContract,
    execute_reference_contract,
)


def test_generated_quran_contract_executes_without_schema_hardcoding():
    contract = GeneratedReferenceContract(
        schema_type="chapter_verse",
        unit="verse",
        identity_fields=("chapter", "verse"),
        canonical_ref_template="{chapter}:{verse}",
        extractors=(
            ContractExtractor(
                type="regex",
                target="page_text",
                pattern=r"\[(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})\]",
            ),
        ),
        acceptance=ContractAcceptance(min_matched_units=2, min_matched_pages=1),
    )

    report = execute_reference_contract(
        contract,
        [SampledPage(page_number=1, text="[1:1] In the name\n[1:2] Praise be")],
    )

    assert report.status == "verified"
    assert report.matched_units == 2
    assert report.matched_pages == [1]
    assert [unit.canonical_reference for unit in report.units] == ["1:1", "1:2"]
    assert report.units[0].provenance == {"page": 1, "target": "page_text"}


def test_generated_contextual_contract_executes_with_context_and_unit_extractors():
    contract = GeneratedReferenceContract(
        schema_type="chapter_verse",
        unit="verse",
        identity_fields=("chapter", "verse"),
        canonical_ref_template="{chapter}:{verse}",
        extractors=(
            ContractExtractor(
                type="contextual_regex",
                target="page_text",
                context_pattern=r"\bSurah\s+(?P<chapter>\d{1,3})\b",
                unit_pattern=r"\b(?P<verse>10[45])\b",
            ),
        ),
        acceptance=ContractAcceptance(min_matched_units=2, min_matched_pages=1),
    )

    report = execute_reference_contract(
        contract,
        [
            SampledPage(
                page_number=168,
                text=(
                    "Surah 7\n"
                    '104 Moses said, "O Pharaoh."\n'
                    "105 I am a messenger."
                ),
            )
        ],
    )

    assert report.status == "verified"
    assert [unit.canonical_reference for unit in report.units] == ["7:104", "7:105"]


def test_generated_contract_rejects_unnamed_identity_groups():
    contract = GeneratedReferenceContract(
        schema_type="chapter_verse",
        unit="verse",
        identity_fields=("chapter", "verse"),
        canonical_ref_template="{chapter}:{verse}",
        extractors=(
            ContractExtractor(
                type="regex",
                target="page_text",
                pattern=r"\[(\d{1,3}):(\d{1,3})\]",
            ),
        ),
        acceptance=ContractAcceptance(min_matched_units=1, min_matched_pages=1),
    )

    report = execute_reference_contract(
        contract,
        [SampledPage(page_number=1, text="[1:1] In the name")],
    )

    assert report.status == "unverified"
    assert report.rejection_reason == "identity_fields_missing_from_extractor"
    assert report.matched_units == 0


def test_generated_contract_rejects_insufficient_evidence():
    contract = GeneratedReferenceContract(
        schema_type="chapter_verse",
        unit="verse",
        identity_fields=("chapter", "verse"),
        canonical_ref_template="{chapter}:{verse}",
        extractors=(
            ContractExtractor(
                type="regex",
                pattern=r"\[(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})\]",
            ),
        ),
        acceptance=ContractAcceptance(min_matched_units=2, min_matched_pages=1),
    )

    report = execute_reference_contract(
        contract,
        [SampledPage(page_number=1, text="[1:1] In the name")],
    )

    assert report.status == "unverified"
    assert report.rejection_reason == "insufficient_matched_units"
    assert report.matched_units == 1


def test_generated_contract_requires_one_extractor_to_satisfy_acceptance():
    contract = GeneratedReferenceContract(
        schema_type="chapter_verse",
        unit="verse",
        identity_fields=("chapter", "verse"),
        canonical_ref_template="{chapter}:{verse}",
        extractors=(
            ContractExtractor(
                type="regex",
                pattern=r"A(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})",
            ),
            ContractExtractor(
                type="regex",
                pattern=r"B(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})",
            ),
        ),
        acceptance=ContractAcceptance(min_matched_units=2, min_matched_pages=1),
    )

    report = execute_reference_contract(
        contract,
        [SampledPage(page_number=1, text="A1:1\nB1:2")],
    )

    assert report.status == "unverified"
    assert report.rejection_reason == "insufficient_extractor_evidence"
    assert report.matched_units == 2
