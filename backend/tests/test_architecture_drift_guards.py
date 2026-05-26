from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

GENERIC_FILES = [
    "backend/src/ragstudio/services/domain_classifier.py",
    "backend/src/ragstudio/services/retrieval_evidence.py",
    "backend/src/ragstudio/services/hybrid_chunk_search.py",
    "backend/src/ragstudio/services/evidence_first_answer_service.py",
    "backend/src/ragstudio/services/domain_metadata_quality_gate.py",
    "backend/src/ragstudio/services/document_parser_service.py",
    "backend/src/ragstudio/services/chunk_service.py",
    "backend/src/ragstudio/services/index_lifecycle_service.py",
    "backend/src/ragstudio/services/mineru_relationship_builder.py",
    "backend/src/ragstudio/services/query_understanding.py",
    "backend/src/ragstudio/services/query_hypothesis_service.py",
    "backend/src/ragstudio/services/query_hypothesis_verifier.py",
    "backend/src/ragstudio/services/retrieval_orchestrator.py",
    "backend/src/ragstudio/services/retrieval_policy.py",
    "backend/src/ragstudio/schemas/chunks.py",
]

DOMAIN_TERMS = [
    "quran",
    "surah",
    "ayah",
    "surah_and_verse",
    "surah_number",
    "chapter_verse",
    "book_hadith",
    "same_chapter",
    "boost_neighbor_verses",
    "next_ayah",
    "previous_ayah",
    '"hadith" in combined',
    '"bukhari" in combined',
]

ADAPTER_ALLOWED_FILES = {
    "backend/src/ragstudio/services/domain_retrieval_adapters.py",
    "backend/src/ragstudio/services/reference_metadata.py",
}

def test_generic_pipeline_files_do_not_reintroduce_domain_specific_terms() -> None:
    offenders: list[str] = []
    for relative_path in GENERIC_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        lowered = text.casefold()
        for term in DOMAIN_TERMS:
            if term.casefold() in lowered:
                offenders.append(f"{relative_path}: {term}")

    assert offenders == []


def test_adapter_files_document_domain_specific_vocabulary_boundary() -> None:
    offenders: list[str] = []
    for relative_path in ADAPTER_ALLOWED_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8").casefold()
        if "adapter" not in text or "generic" not in text:
            offenders.append(relative_path)

    assert offenders == []


def test_reference_contract_inventory_records_proof_boundary() -> None:
    inventory = (
        REPO_ROOT / "docs/architecture/hardcoded-policy-inventory.md"
    ).read_text(encoding="utf-8")
    lowered = inventory.casefold()

    assert "identity.fields" in inventory
    assert "verified executable reference contracts" in lowered
    assert "metadata-only reference hints" in lowered
