import pytest
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_metadata_ai_suggester import DomainMetadataAiSuggester
from ragstudio.services.page_sampler import SampledPage
from ragstudio.services.reference_contract_execution import execute_reference_contract
from ragstudio.services.reference_contract_validator import ReferenceContractValidator
from ragstudio.services.reference_contracts import build_executable_reference_contract


def test_autosuggest_prompt_keeps_legacy_model_facing_body():
    prompt = DomainMetadataAiSuggester()._prompt(
        filename="sample.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Sample text")],
    )

    assert prompt.startswith("You classify documents for a RAG indexing system.")
    assert "Prompt id:" not in prompt
    assert "Prompt version:" not in prompt


def test_reference_contract_candidates_include_declared_groups_and_template():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "fields": {"folio": "folio_number", "line": "line_number"},
                "canonical_ref_template": "folio:{folio}:line:{line}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
                    "unit": "folio_line",
                },
                "context_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)",
                    "unit": "folio",
                },
                "unit_anchor": {
                    "regex": r"Line\s+(?P<line>\d+)",
                    "unit": "line",
                },
            },
        }
    )

    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )

    single_anchor = next(candidate for candidate in candidates if candidate.primary_anchor_regex)
    contextual = next(candidate for candidate in candidates if candidate.context_anchor_regex)
    assert single_anchor.required_groups == frozenset({"folio", "line"})
    assert single_anchor.canonical_ref_template == "folio:{folio}:line:{line}"
    assert contextual.required_groups == frozenset({"folio", "line"})
    assert contextual.context_required_groups == frozenset({"folio"})
    assert contextual.unit_required_groups == frozenset({"line"})
    assert contextual.canonical_ref_template == "folio:{folio}:line:{line}"


def test_quran_like_candidate_uses_template_identity_not_page_field():
    custom_json = {
        "reference_schema": {
            "type": "quran_tafseer",
            "fields": {
                "chapter": "chapter_number",
                "verse": "verse_number",
                "page": "page_number",
            },
            "canonical_ref_template": "{chapter}:{verse}",
        },
        "domain_structure": {
            "primary_anchor": {
                "regex": r"\[(?P<chapter>\d+):(?P<verse>\d+)\]",
                "unit": "verse",
                "verified": True,
            },
        },
    }
    metadata = DomainMetadata(custom_json=custom_json)
    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )
    validation = ReferenceContractValidator().validate(
        [SampledPage(page_number=1, text="[1:1] [1:2]")],
        candidates,
    )
    contract = build_executable_reference_contract(custom_json)

    assert contract.required_groups == frozenset({"chapter", "verse"})
    assert contract.verified is True
    assert candidates[0].required_groups == frozenset({"chapter", "verse"})
    assert validation.status == "verified"
    assert validation.selected is not None
    assert validation.selected.required_groups_present is True
    assert validation.selected.matched_units == 2
    assert [example["reference"] for example in validation.selected.examples] == [
        "1:1",
        "1:2",
    ]


def test_reference_contract_candidates_accept_model_generated_executable_contract():
    metadata = DomainMetadata(
        custom_json={
            "reference_contract_candidates": [
                {
                    "schema_type": "chapter_verse",
                    "unit": "verse",
                    "identity": {
                        "fields": ["chapter", "verse"],
                        "canonical_ref_template": "{chapter}:{verse}",
                    },
                    "extractors": [
                        {
                            "type": "regex",
                            "target": "page_text",
                            "pattern": (
                                r"\[(?P<chapter>\d{1,3}):"
                                r"(?P<verse>\d{1,3})\]"
                            ),
                        }
                    ],
                    "acceptance": {"min_matched_units": 2, "min_matched_pages": 1},
                }
            ]
        }
    )

    contracts = DomainMetadataAiSuggester()._generated_reference_contracts(metadata)
    report = execute_reference_contract(
        contracts[0],
        [SampledPage(page_number=1, text="[1:1]\n[1:2]")],
    )

    assert report.status == "verified"
    assert report.matched_units == 2
    assert report.units[0].canonical_reference == "1:1"


def test_generated_contract_execution_marks_verified_contract():
    metadata = DomainMetadata(
        custom_json={
            "reference_contract_candidates": [
                {
                    "schema_type": "chapter_verse",
                    "unit": "verse",
                    "identity": {
                        "fields": ["chapter", "verse"],
                        "canonical_ref_template": "{chapter}:{verse}",
                    },
                    "extractors": [
                        {
                            "type": "regex",
                            "target": "page_text",
                            "pattern": (
                                r"\[(?P<chapter>\d{1,3}):"
                                r"(?P<verse>\d{1,3})\]"
                            ),
                        }
                    ],
                    "acceptance": {"min_matched_units": 2, "min_matched_pages": 1},
                }
            ]
        }
    )
    suggester = DomainMetadataAiSuggester()
    contracts = suggester._generated_reference_contracts(metadata)

    result = suggester._apply_generated_contract_execution(
        metadata,
        contracts,
        [SampledPage(page_number=1, text="[1:1]\n[1:2]")],
    )
    contract = build_executable_reference_contract(result.custom_json)

    assert result.custom_json["reference_contract_execution"]["status"] == "verified"
    assert result.custom_json["reference_contract_validation"]["status"] == "verified"
    assert result.custom_json["reference_contract_validation"]["selected_strategy"] == (
        "single_anchor"
    )
    assert contract.verified is True


def test_generated_contract_execution_keeps_failed_contract_metadata_only():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {"type": "chapter_verse"},
            "reference_contract_candidates": [
                {
                    "schema_type": "chapter_verse",
                    "unit": "verse",
                    "identity": {
                        "fields": ["chapter", "verse"],
                        "canonical_ref_template": "{chapter}:{verse}",
                    },
                    "extractors": [
                        {
                            "type": "regex",
                            "target": "page_text",
                            "pattern": r"\[(\d{1,3}):(\d{1,3})\]",
                        }
                    ],
                }
            ],
        }
    )
    suggester = DomainMetadataAiSuggester()
    contracts = suggester._generated_reference_contracts(metadata)

    result = suggester._apply_generated_contract_execution(
        metadata,
        contracts,
        [SampledPage(page_number=1, text="[1:1]")],
    )
    contract = build_executable_reference_contract(result.custom_json)

    assert result.custom_json["reference_contract_execution"]["status"] == "unverified"
    assert result.custom_json["reference_contract_validation"]["status"] == "unverified"
    assert "reference_resolution" not in result.custom_json
    assert contract.verified is False


@pytest.mark.asyncio
async def test_suggest_preserves_template_identity_through_validation(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "domain_metadata": {
                                "domain": "quran_tafseer",
                                "custom_json": {
                                  "reference_schema": {
                                    "type": "quran_tafseer",
                                    "fields": {
                                      "chapter": "chapter_number",
                                      "verse": "verse_number",
                                      "page": "page_number"
                                    },
                                    "canonical_ref_template": "{chapter}:{verse}"
                                  },
                                  "domain_structure": {
                                    "primary_anchor": {
                                      "regex": "\\\\[(?P<chapter>\\\\d+):(?P<verse>\\\\d+)\\\\]",
                                      "unit": "verse"
                                    }
                                  }
                                }
                              },
                              "confidence": 0.9,
                              "evidence_pages": [1],
                              "rationale": "The sampled page shows bracketed references.",
                              "warnings": []
                            }
                            """
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="text-model",
            llm_base_url="http://llm.test/v1",
            embedding_model="embedding-model",
            storage_backend="postgres",
            vision_model="vision-model",
            vision_base_url="http://vision.test/v1",
        ),
        filename="quran.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="[1:1] [1:2]")],
        sampler_warnings=[],
    )

    custom_json = result.domain_metadata.custom_json
    reference_schema = custom_json["reference_schema"]
    contract = build_executable_reference_contract(custom_json)

    assert reference_schema["canonical_ref_template"] == "{chapter}:{verse}"
    assert custom_json["reference_contract_validation"]["status"] == "verified"
    assert contract.required_groups == frozenset({"chapter", "verse"})
    assert contract.verified is True


@pytest.mark.asyncio
async def test_suggest_derives_missing_template_identity_fields(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "domain_metadata": {
                                "domain": "quran_tafseer",
                                "custom_json": {
                                  "reference_schema": {
                                    "type": "chapter_verse",
                                    "canonical_ref_template": "{chapter}:{verse}"
                                  },
                                  "domain_structure": {
                                    "primary_anchor": {
                                      "regex": "\\\\[(?P<chapter>\\\\d+):(?P<verse>\\\\d+)\\\\]",
                                      "unit": "verse"
                                    }
                                  }
                                }
                              },
                              "confidence": 0.9,
                              "evidence_pages": [1],
                              "rationale": "The sampled page shows bracketed references.",
                              "warnings": []
                            }
                            """
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="text-model",
            llm_base_url="http://llm.test/v1",
            embedding_model="embedding-model",
            storage_backend="postgres",
            vision_model="vision-model",
            vision_base_url="http://vision.test/v1",
        ),
        filename="quran.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="[1:1] [1:2]")],
        sampler_warnings=[],
    )

    custom_json = result.domain_metadata.custom_json
    reference_schema = custom_json["reference_schema"]
    contract = build_executable_reference_contract(custom_json)

    assert reference_schema["canonical_ref_template"] == "{chapter}:{verse}"
    assert reference_schema["identity_fields"] == ["chapter", "verse"]
    assert custom_json["reference_contract_validation"]["status"] == "verified"
    assert contract.required_groups == frozenset({"chapter", "verse"})
    assert contract.verified is True


@pytest.mark.asyncio
async def test_suggest_executes_model_generated_contract_candidate(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "domain_metadata": {
                                "domain": "scripture",
                                "custom_json": {
                                  "reference_contract_candidates": [
                                    {
                                      "schema_type": "chapter_verse",
                                      "unit": "verse",
                                      "identity": {
                                        "fields": ["chapter", "verse"],
                                        "canonical_ref_template": "{chapter}:{verse}"
                                      },
                                      "extractors": [
                                        {
                                          "type": "regex",
                                          "target": "page_text",
                                          "pattern": "\\\\[(?P<chapter>\\\\d):(?P<verse>\\\\d)\\\\]"
                                        }
                                      ],
                                      "acceptance": {
                                        "min_matched_units": 2,
                                        "min_matched_pages": 1
                                      }
                                    }
                                  ]
                                }
                              },
                              "confidence": 0.9,
                              "evidence_pages": [1],
                              "rationale": "The sampled page shows bracketed references.",
                              "warnings": []
                            }
                            """
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="text-model",
            llm_base_url="http://llm.test/v1",
            embedding_model="embedding-model",
            storage_backend="postgres",
            vision_model="vision-model",
            vision_base_url="http://vision.test/v1",
        ),
        filename="quran.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="[1:1] [1:2]")],
        sampler_warnings=[],
    )

    custom_json = result.domain_metadata.custom_json
    contract = build_executable_reference_contract(custom_json)

    assert custom_json["reference_contract_execution"]["status"] == "verified"
    assert custom_json["reference_contract_validation"]["selected_source"] == (
        "ai_generated_contract"
    )
    assert custom_json["reference_resolution"]["build_canonical_units"] is True
    assert contract.verified is True
    assert result.reference_contract_validation is not None
    assert result.reference_contract_validation["status"] == "verified"


@pytest.mark.asyncio
async def test_suggest_falls_back_to_legacy_validation_when_generated_contract_fails(
    monkeypatch,
):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "domain_metadata": {
                                "domain": "scripture",
                                "custom_json": {
                                  "reference_schema": {
                                    "type": "chapter_verse",
                                    "fields": {
                                      "chapter": "chapter_number",
                                      "verse": "verse_number"
                                    },
                                    "canonical_ref_template": "{chapter}:{verse}"
                                  },
                                  "domain_structure": {
                                    "primary_anchor": {
                                      "regex": "\\\\[(?P<chapter>\\\\d+):(?P<verse>\\\\d+)\\\\]",
                                      "unit": "verse"
                                    }
                                  },
                                  "reference_contract_candidates": [
                                    {
                                      "schema_type": "chapter_verse",
                                      "unit": "verse",
                                      "identity": {
                                        "fields": ["chapter", "verse"],
                                        "canonical_ref_template": "{chapter}:{verse}"
                                      },
                                      "extractors": [
                                        {
                                          "type": "regex",
                                          "target": "page_text",
                                          "pattern": "\\\\[(?P<chapter>\\\\d+)\\\\]"
                                        }
                                      ],
                                      "acceptance": {
                                        "min_matched_units": 2,
                                        "min_matched_pages": 1
                                      }
                                    }
                                  ]
                                }
                              },
                              "confidence": 0.9,
                              "evidence_pages": [1],
                              "rationale": "The sampled page shows bracketed references.",
                              "warnings": []
                            }
                            """
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="text-model",
            llm_base_url="http://llm.test/v1",
            embedding_model="embedding-model",
            storage_backend="postgres",
            vision_model="vision-model",
            vision_base_url="http://vision.test/v1",
        ),
        filename="quran.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="[1:1] [1:2]")],
        sampler_warnings=[],
    )

    custom_json = result.domain_metadata.custom_json
    contract = build_executable_reference_contract(custom_json)

    assert custom_json["reference_contract_execution"]["status"] == "unverified"
    assert custom_json["reference_contract_validation"]["status"] == "verified"
    assert custom_json["reference_contract_validation"]["selected_source"] == "ai_observed"
    assert custom_json["reference_resolution"]["build_canonical_units"] is True
    assert contract.verified is True


def test_malformed_template_candidate_fails_without_throwing():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "fields": {"folio": "folio_number", "line": "line_number"},
                "canonical_ref_template": "folio:{folio:line:{line}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
                    "unit": "folio_line",
                }
            },
        }
    )

    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )
    result = ReferenceContractValidator().validate(
        [SampledPage(page_number=1, text="Folio 12 Line 7")],
        candidates,
    )

    assert candidates[0].required_groups == frozenset({"folio", "line"})
    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].matched_units == 0


def test_production_candidate_rejects_empty_required_capture():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "article_clause",
                "fields": {"article": "article_number", "clause": "clause_number"},
                "canonical_ref_template": "article:{article}:clause:{clause}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Article\s+(?P<article>\d+)\.(?P<clause>\d*)",
                    "unit": "article_clause",
                }
            },
        }
    )
    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )

    result = ReferenceContractValidator().validate(
        [
            SampledPage(
                page_number=1,
                text="Article 12. The procedure starts here.",
            )
        ],
        candidates,
    )

    assert candidates[0].required_groups == frozenset({"article", "clause"})
    assert candidates[0].canonical_ref_template == "article:{article}:clause:{clause}"
    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].required_groups_present is True
    assert result.candidates[0].matched_units == 0
    assert result.candidates[0].examples == []


def test_contextual_production_candidate_missing_declared_field_does_not_verify():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "article_clause_item",
                "fields": {
                    "article": "article_number",
                    "clause": "clause_number",
                    "item": "item_number",
                },
                "canonical_ref_template": "article:{article}:clause:{clause}:item:{item}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": r"Article\s+(?P<article>\d+)",
                    "unit": "article",
                },
                "unit_anchor": {
                    "regex": r"Clause\s+(?P<clause>\d+)",
                    "unit": "clause",
                },
            },
        }
    )
    candidates = DomainMetadataAiSuggester()._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )

    result = ReferenceContractValidator().validate(
        [
            SampledPage(
                page_number=1,
                text="Article 12\nClause 7 The procedure starts here.",
            )
        ],
        candidates,
    )

    assert candidates[0].required_groups == frozenset({"article", "clause", "item"})
    assert candidates[0].context_required_groups == frozenset({"article"})
    assert candidates[0].unit_required_groups == frozenset({"clause"})
    assert result.status == "unverified"
    assert result.selected is None
    assert result.candidates[0].required_groups_present is False
    assert result.candidates[0].matched_units == 0


def test_contextual_contract_validation_uses_generic_declared_context_unit():
    metadata = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "fields": {"folio": "folio_number", "line": "line_number"},
                "canonical_ref_template": "folio:{folio}:line:{line}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)",
                },
                "unit_anchor": {
                    "regex": r"Line\s+(?P<line>\d+)",
                    "unit": "line",
                },
            },
        }
    )
    suggester = DomainMetadataAiSuggester()
    candidates = suggester._reference_contract_candidates(
        metadata,
        source="ai_observed",
    )
    validation = ReferenceContractValidator().validate(
        [
            SampledPage(
                page_number=1,
                text="Folio 12\nLine 7 The note starts here.",
            )
        ],
        candidates,
    )

    result = suggester._apply_reference_contract_validation(metadata, validation)

    domain_structure = result.custom_json["domain_structure"]
    context_anchor = domain_structure["context_anchor"]
    assert validation.status == "verified"
    assert context_anchor["verified"] is True
    assert context_anchor["unit"] == "folio"
    assert context_anchor["unit"] != "chapter"
