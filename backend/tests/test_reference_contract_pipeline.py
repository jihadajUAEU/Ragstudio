from __future__ import annotations

import json
from pathlib import Path

from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.document_contract import build_document_index_contract
from ragstudio.services.domain_metadata_ai_suggester import DomainMetadataAiSuggester
from ragstudio.services.domain_metadata_contract_compiler import compile_domain_metadata
from ragstudio.services.page_sampler import SampledPage
from ragstudio.services.reference_contract_validator import ReferenceContractValidator

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reference_contracts"


def test_custom_reference_contract_survives_validation_compile_and_index_contract():
    payload = _fixture("folio_line_sample.json")
    metadata = DomainMetadata.model_validate(payload["domain_metadata"])
    pages = _sampled_pages(payload)
    suggester = DomainMetadataAiSuggester(http_client_provider=None)
    candidates = suggester._reference_contract_candidates(metadata, source="fixture")

    validation = ReferenceContractValidator().validate(pages, candidates)
    custom_json = dict(metadata.custom_json or {})
    custom_json["reference_contract_validation"] = validation.to_payload()
    metadata = metadata.model_copy(update={"custom_json": custom_json}, deep=True)

    compiled = compile_domain_metadata(metadata)
    contract = build_document_index_contract(IndexDocumentIn(domain_metadata=compiled))

    assert validation.status == "verified"
    assert compiled.custom_json is not None
    assert compiled.custom_json["reference_schema"]["type"] == "folio_line"
    assert compiled.custom_json["domain_structure"]["primary_anchor"]["verified"] is True
    assert contract["reference_contract"]["verified"] is True
    assert contract["reference_contract"]["schema_type"] == "folio_line"
    assert contract["reference_contract"]["canonical_ref_template"] == "folio:{folio}:line:{line}"


def test_contextual_contract_survives_validation_compile_and_index_contract():
    payload = _fixture("quran_contextual_sample.json")
    metadata = DomainMetadata.model_validate(payload["domain_metadata"])
    pages = _sampled_pages(payload)
    suggester = DomainMetadataAiSuggester(http_client_provider=None)
    candidates = suggester._reference_contract_candidates(metadata, source="fixture")

    validation = ReferenceContractValidator().validate(pages, candidates)
    custom_json = dict(metadata.custom_json or {})
    custom_json["reference_contract_validation"] = validation.to_payload()
    metadata = metadata.model_copy(update={"custom_json": custom_json}, deep=True)

    compiled = compile_domain_metadata(metadata)
    contract = build_document_index_contract(IndexDocumentIn(domain_metadata=compiled))

    assert validation.status == "verified"
    assert compiled.custom_json is not None
    assert compiled.custom_json["domain_structure"]["context_anchor"]["verified"] is True
    assert compiled.custom_json["domain_structure"]["unit_anchor"]["verified"] is True
    assert contract["reference_contract"]["verified"] is True
    assert contract["reference_contract"]["strategy"] == "contextual_unit"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _sampled_pages(payload: dict[str, object]) -> list[SampledPage]:
    raw_pages = payload["pages"]
    assert isinstance(raw_pages, list)
    return [
        SampledPage(page_number=int(page["page_number"]), text=str(page["text"]))
        for page in raw_pages
        if isinstance(page, dict)
    ]
