import pytest
from ragstudio.services.evidence_unit_contract import (
    EvidenceUnit,
    MaterializationPolicy,
    PageBlockProvenance,
    QualityActionPolicy,
)


def test_evidence_unit_serializes_required_contract_fields():
    unit = EvidenceUnit(
        document_id="doc-1",
        chunk_id="chunk-1",
        runtime_source_id="runtime-doc-1",
        unit_type="reference",
        canonical_reference="Article 4 / Page 2",
        provenance=PageBlockProvenance(
            page_number=2,
            block_id="block-7",
            block_type="paragraph",
            reading_order=4,
        ),
        quality_action_policy=QualityActionPolicy(action="warn", reasons=("low_ocr_confidence",)),
        materialization_policy=MaterializationPolicy(action="index_vector"),
    )

    payload = unit.as_dict()

    assert payload["document_id"] == "doc-1"
    assert payload["chunk_id"] == "chunk-1"
    assert payload["runtime_source_id"] == "runtime-doc-1"
    assert payload["unit_type"] == "reference"
    assert payload["canonical_reference"] == "Article 4 / Page 2"
    assert payload["page_block_provenance"] == {
        "page_number": 2,
        "block_id": "block-7",
        "block_type": "paragraph",
        "reading_order": 4,
    }
    assert payload["quality_action_policy"]["action"] == "warn"
    assert payload["materialization_policy"]["source_of_truth"] == "postgres_canonical_evidence"


def test_evidence_unit_rejects_missing_stable_identifiers():
    with pytest.raises(ValueError, match="document_id"):
        EvidenceUnit(
            document_id="",
            chunk_id="chunk-1",
            runtime_source_id="runtime-doc-1",
            unit_type="text",
            canonical_reference="Page 1",
            provenance=PageBlockProvenance(page_number=1),
        )
