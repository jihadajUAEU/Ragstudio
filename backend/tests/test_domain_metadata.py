import json

import httpx
import pytest
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata, DomainMetadataSuggestOut
from ragstudio.services.domain_metadata_ai_suggester import (
    BASELINE_PROMPT_MAX_DICT_ITEMS,
    BASELINE_PROMPT_MAX_LIST,
    BASELINE_PROMPT_MAX_STRING,
    DomainMetadataAiSuggester,
)
from ragstudio.services.domain_metadata_service import DomainMetadataService
from ragstudio.services.metadata_json_schema import validate_custom_json
from ragstudio.services.page_sampler import SampledPage


def test_builtin_profiles_have_valid_conservative_custom_json(tmp_path):
    profiles = DomainMetadataService(tmp_path).list_profiles()

    assert {profile.id for profile in profiles} == {
        "generic",
        "research_paper",
        "policy_admin",
        "table_spreadsheet",
        "hadith",
        "quran_tafseer",
        "fatwa_fiqh",
    }
    for profile in profiles:
        validate_custom_json(profile.metadata.custom_json)
        assert profile.metadata.source is None
        assert profile.metadata.authority is None
        if profile.id != "generic":
            assert profile.metadata.tags


def test_builtin_hadith_profile_has_book_hadith_reference_semantics(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("hadith")

    assert profile is not None
    assert profile.metadata.domain == "hadith"
    assert profile.metadata.citation_style == "book_hadith"
    assert profile.metadata.custom_json == {
        "reference_schema": {
            "type": "book_hadith",
            "display": "Book {book}, Hadith {hadith}",
            "canonical_ref_template": "book:{book}:hadith:{hadith}",
            "fields": {
                "book": "book_number",
                "hadith": "hadith_number",
                "chapter": "chapter_title",
            },
        },
        "relationships": {
            "previous": ["same_book", "hadith - 1"],
            "next": ["same_book", "hadith + 1"],
            "book": ["same_book"],
            "chapter": ["same_chapter"],
        },
        "chunking": {
            "unit": "hadith",
            "include_neighbors": 1,
            "preserve_parallel_text": True,
            "merge_reference_header_with_body": True,
        },
        "reference_resolution": {
            "enabled": True,
            "build_canonical_units": True,
            "carry_forward_body_blocks": True,
            "header_only_policy": "provenance_only",
            "continuation_policy": "until_next_reference",
            "max_page_gap": 2,
            "require_single_reference_per_answerable_chunk": True,
        },
        "provenance": {
            "preserve_original_blocks": True,
            "block_preview_chars": 160,
            "store_text_hash": True,
        },
        "parser_normalization": {
            "allow_equations_as_content": False,
            "recover_text_bearing_blocks_as_prose": True,
            "preserve_original_block_type": True,
        },
        "retrieval": {
            "exact_reference_top1": True,
            "boost_same_chapter": True,
            "boost_neighbor_verses": True,
        },
        "graph": {
            "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
            "edge_types": [
                "contains",
                "references",
                "next_hadith",
                "same_book",
                "same_chapter",
            ],
            "materialize_from": ["mineru_structure", "reference_metadata"],
            "confidence_policy": "evidence_required",
        },
    }


def test_builtin_quran_profile_has_chapter_verse_reference_semantics(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("quran_tafseer")

    assert profile is not None
    assert profile.metadata.citation_style == "surah_ayah"
    assert profile.metadata.custom_json["reference_schema"]["type"] == "chapter_verse"
    assert profile.metadata.custom_json["reference_schema"]["canonical_ref_template"] == (
        "{chapter}:{verse}"
    )
    assert profile.metadata.custom_json["chunking"]["unit"] == "verse"
    assert profile.metadata.custom_json["chunking"]["merge_reference_header_with_body"] is True
    assert (
        profile.metadata.custom_json["reference_resolution"]["build_canonical_units"] is True
    )
    assert profile.metadata.custom_json["reference_resolution"]["header_only_policy"] == (
        "provenance_only"
    )
    assert profile.metadata.custom_json["provenance"]["preserve_original_blocks"] is True
    assert profile.metadata.custom_json["parser_normalization"] == {
        "allow_equations_as_content": False,
        "recover_text_bearing_blocks_as_prose": True,
        "preserve_original_block_type": True,
    }
    assert profile.metadata.custom_json["graph"]["node_types"] == [
        "surah",
        "ayah",
        "translation",
        "chunk",
    ]
    assert "references" in profile.metadata.custom_json["graph"]["edge_types"]
    assert profile.metadata.custom_json["retrieval"]["exact_reference_top1"] is True


def test_builtin_profiles_have_domain_specific_parser_normalization(tmp_path):
    profiles = {profile.id: profile for profile in DomainMetadataService(tmp_path).list_profiles()}

    assert profiles["generic"].metadata.custom_json["parser_normalization"] == {
        "allow_equations_as_content": False,
        "recover_text_bearing_blocks_as_prose": False,
        "preserve_original_block_type": True,
    }
    assert profiles["research_paper"].metadata.custom_json["parser_normalization"] == {
        "allow_equations_as_content": True,
        "recover_text_bearing_blocks_as_prose": False,
        "preserve_original_block_type": True,
    }
    assert profiles["table_spreadsheet"].metadata.custom_json["parser_normalization"] == {
        "allow_equations_as_content": True,
        "recover_text_bearing_blocks_as_prose": True,
        "preserve_original_block_type": True,
    }
    for profile_id in ("policy_admin", "hadith", "quran_tafseer", "fatwa_fiqh"):
        assert profiles[profile_id].metadata.custom_json["parser_normalization"] == {
            "allow_equations_as_content": False,
            "recover_text_bearing_blocks_as_prose": True,
            "preserve_original_block_type": True,
        }


@pytest.mark.asyncio
async def test_domain_profiles_include_general_and_islamic_builtins(client):
    response = await client.get("/api/domain-profiles")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "Generic document" in names
    assert "Research paper" in names
    assert "Policy/admin document" in names
    assert "Table/spreadsheet" in names
    assert "Hadith" in names
    assert "Quran/Tafseer" in names
    assert "Fatwa/Fiqh" in names


@pytest.mark.asyncio
async def test_reference_json_example_endpoint(client):
    response = await client.get("/api/domain-profiles/reference-json-example")

    assert response.status_code == 200
    custom_json = response.json()["custom_json"]
    assert "reference_schema" in custom_json
    assert "chunking" in custom_json
    assert "retrieval" in custom_json


def test_validate_custom_json_accepts_quran_style_relationships():
    custom_json = {
        "reference_schema": {
            "type": "surah_ayah",
            "display": "Quran {chapter}:{verse}",
            "canonical_ref_template": "{chapter}:{verse}",
            "fields": {
                "chapter": "surah",
                "verse": "ayah",
                "page": "page_start",
            },
        },
        "relationships": {
            "previous": ["same_chapter", "verse - 1"],
            "next": ["same_chapter", "verse + 1"],
            "chapter": ["same_chapter"],
            "page": ["same_page"],
        },
        "chunking": {
            "unit": "verse",
            "include_neighbors": 1,
            "preserve_parallel_text": True,
            "merge_reference_header_with_body": True,
        },
        "reference_resolution": {
            "enabled": True,
            "build_canonical_units": True,
            "carry_forward_body_blocks": True,
            "header_only_policy": "provenance_only",
            "continuation_policy": "until_next_reference",
            "max_page_gap": 1,
            "require_single_reference_per_answerable_chunk": True,
        },
        "provenance": {
            "preserve_original_blocks": True,
            "block_preview_chars": 160,
            "store_text_hash": True,
        },
        "retrieval": {
            "exact_reference_top1": True,
            "boost_same_chapter": True,
            "boost_neighbor_verses": True,
        },
    }

    assert validate_custom_json(custom_json) is custom_json


def test_validate_custom_json_accepts_graph_semantics():
    payload = {
        "graph": {
            "node_types": ["surah", "ayah", "chunk"],
            "edge_types": ["contains", "next_ayah", "references"],
            "materialize_from": ["mineru_structure", "reference_metadata"],
            "confidence_policy": "evidence_required",
        }
    }

    assert validate_custom_json(payload) == payload


def test_validate_custom_json_rejects_invalid_graph_node_types():
    with pytest.raises(ValueError, match=r"custom_json\.graph\.node_types"):
        validate_custom_json({"graph": {"node_types": ["chunk", 42]}})


def test_validate_custom_json_rejects_invalid_graph_confidence_policy():
    with pytest.raises(ValueError, match=r"custom_json\.graph\.confidence_policy"):
        validate_custom_json({"graph": {"confidence_policy": "guess_allowed"}})


def test_validate_custom_json_rejects_missing_graph_confidence_policy():
    with pytest.raises(ValueError, match=r"custom_json\.graph\.confidence_policy"):
        validate_custom_json({"graph": {"edge_types": ["references"]}})


def test_validate_custom_json_rejects_invalid_include_neighbors_boolean():
    with pytest.raises(ValueError, match="include_neighbors"):
        validate_custom_json({"chunking": {"include_neighbors": True}})


def test_validate_custom_json_rejects_invalid_retrieval_booleans():
    with pytest.raises(ValueError, match="retrieval values must be booleans"):
        validate_custom_json({"retrieval": {"exact_reference_top1": "true"}})

    with pytest.raises(ValueError, match="retrieval values must be booleans"):
        validate_custom_json({"retrieval": {"boost_same_chapter": 1}})


def test_validate_custom_json_rejects_invalid_reference_resolution():
    with pytest.raises(ValueError, match=r"reference_resolution\.build_canonical_units"):
        validate_custom_json({"reference_resolution": {"build_canonical_units": "true"}})

    with pytest.raises(ValueError, match=r"reference_resolution\.max_page_gap"):
        validate_custom_json({"reference_resolution": {"max_page_gap": -1}})


def test_validate_custom_json_rejects_invalid_provenance_contract():
    with pytest.raises(ValueError, match=r"provenance\.preserve_original_blocks"):
        validate_custom_json({"provenance": {"preserve_original_blocks": "yes"}})

    with pytest.raises(ValueError, match=r"provenance\.block_preview_chars"):
        validate_custom_json({"provenance": {"block_preview_chars": True}})


def test_validate_custom_json_rejects_invalid_parser_normalization_contract():
    with pytest.raises(ValueError, match=r"parser_normalization\.allow_equations"):
        validate_custom_json({"parser_normalization": {"allow_equations_as_content": "false"}})

    with pytest.raises(ValueError, match=r"parser_normalization\.allowed_block_types"):
        validate_custom_json({"parser_normalization": {"allowed_block_types": ["text", 42]}})


def test_validate_custom_json_rejects_invalid_reference_regex():
    with pytest.raises(ValueError, match="valid regex"):
        validate_custom_json(
            {"reference_schema": {"type": "legal_section", "pattern": "(?P<section>"}}
        )


def test_validate_custom_json_rejects_unsafe_reference_regex():
    with pytest.raises(ValueError, match="nested or adjacent quantifiers"):
        validate_custom_json(
            {"reference_schema": {"type": "legal_section", "pattern": r"(?P<section>(a+)+)"}}
        )


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_uses_vision_model(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "quran_tafseer",
                                "document_type": "commentary",
                                "language": "mixed",
                                "tags": ["quran", "tafseer"],
                                "citation_style": "surah_ayah",
                                "expected_structure": "surah_ayah_sections",
                                "script": "mixed",
                                "content_role": "tafseer",
                                "metadata_sources": ["model_supplied"]
                              },
                              "confidence": 0.92,
                              "evidence_pages": [1, 99],
                              "rationale": "Sample pages show Quran verses and commentary.",
                              "warnings": []
                            }"""
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
            calls.append({"url": url, "headers": headers, "json": json})
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
            vision_api_key="vision-secret",
        ),
        filename="tafseer.txt",
        content_type="text/plain",
        pages=[
            SampledPage(
                page_number=1,
                text="Surah Al-Fatiha tafseer commentary",
                image_data_url="data:image/png;base64,abc",
            )
        ],
        sampler_warnings=["sample warning"],
    )

    assert result.domain_metadata.domain == "quran_tafseer"
    assert result.domain_metadata.metadata_sources == ["ai_vision"]
    assert result.confidence == 0.92
    assert result.evidence_pages == [1]
    assert result.rationale == "Sample pages show Quran verses and commentary."
    assert result.warnings == ["sample warning"]
    assert calls[0]["url"] == "http://vision.test/v1/chat/completions"
    assert calls[0]["headers"]["authorization"] == "Bearer vision-secret"
    assert calls[0]["json"]["model"] == "vision-model"
    assert calls[0]["json"]["temperature"] == 0
    assert calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert calls[0]["json"]["messages"][0]["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_uses_images_for_vision_capable_llm(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "research",
                                "document_type": "paper",
                                "tags": ["paper"],
                                "metadata_sources": ["model_supplied"]
                              },
                              "confidence": 0.7,
                              "evidence_pages": [2],
                              "rationale": "The page image shows a paper layout.",
                              "warnings": []
                            }"""
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
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="paper.pdf",
        content_type="application/pdf",
        pages=[
            SampledPage(
                page_number=2,
                text="",
                image_data_url="data:image/png;base64,abc",
            )
        ],
        sampler_warnings=[],
    )

    assert result.domain_metadata.metadata_sources == ["ai_vision"]
    assert result.evidence_pages == [2]
    assert calls[0]["url"] == "http://llm.test/v1/chat/completions"
    assert calls[0]["json"]["messages"][0]["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_uses_minimum_autosuggest_timeout(monkeypatch):
    timeouts = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "research",
                                "document_type": "paper",
                                "tags": ["paper"]
                              },
                              "confidence": 0.7,
                              "evidence_pages": [1],
                              "rationale": "The page shows a paper.",
                              "warnings": []
                            }"""
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            timeouts.append(timeout)

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

    await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_timeout_ms=5000,
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="paper.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Research paper")],
        sampler_warnings=[],
    )

    assert timeouts == [60]


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_preserves_reference_custom_json(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "reference_text",
                                "document_type": "annotated_source",
                                "language": "mixed",
                                "tags": ["reference-heavy"],
                                "reference_pattern": "chapter:verse",
                                "expected_structure": "numbered_reference_units",
                                "custom_json": {
                                  "reference_schema": {
                                    "type": "chapter_verse",
                                    "display": "{chapter}:{verse}",
                                    "fields": {
                                      "chapter": "chapter_number",
                                      "verse": "verse_number",
                                      "page": "page_number"
                                    }
                                  },
                                  "relationships": {
                                    "previous": ["same_chapter", "verse - 1"],
                                    "next": ["same_chapter", "verse + 1"],
                                    "page": ["same_page"]
                                  },
                                  "chunking": {
                                    "unit": "verse",
                                    "include_neighbors": 1,
                                    "preserve_parallel_text": true
                                  },
                                  "retrieval": {
                                    "exact_reference_top1": true,
                                    "boost_neighbor_verses": true
                                  }
                                },
                                "metadata_sources": ["model_supplied"]
                              },
                              "confidence": 0.86,
                              "evidence_pages": [1, 2, 3, 4],
                              "rationale": "Samples show repeated structured references.",
                              "warnings": []
                            }"""
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
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="reference-text.pdf",
        content_type="application/pdf",
        pages=[
            SampledPage(
                page_number=page_number,
                text=f"[1:{page_number}] Structured referenced text",
                image_data_url=f"data:image/png;base64,page{page_number}",
            )
            for page_number in range(1, 6)
        ],
        sampler_warnings=[],
    )

    prompt = calls[0]["json"]["messages"][0]["content"][0]["text"]
    assert "custom_json.reference_schema" in prompt
    assert "custom_json.relationships" in prompt
    assert "custom_json.chunking" in prompt
    assert "custom_json.retrieval" in prompt
    assert "legal sections/subsections" in prompt
    assert "page-line references" in prompt
    assert "Page 4 text excerpt" in prompt
    assert "Page 5 text excerpt" not in prompt
    assert len(calls[0]["json"]["messages"][0]["content"]) == 5

    custom_json = result.domain_metadata.custom_json
    assert custom_json["reference_schema"]["type"] == "chapter_verse"
    assert custom_json["reference_schema"]["fields"]["verse"] == "verse_number"
    assert custom_json["relationships"]["next"] == ["same_chapter", "verse + 1"]
    assert custom_json["chunking"]["unit"] == "verse"
    assert custom_json["chunking"]["include_neighbors"] == 1
    assert custom_json["retrieval"]["exact_reference_top1"] is True
    assert custom_json["retrieval"]["boost_neighbor_verses"] is True
    assert result.domain_metadata.metadata_sources == ["ai_vision"]


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_prunes_invalid_custom_json_shapes(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "quran_tafseer",
                                "document_type": "commentary",
                                "tags": ["quran"],
                                "custom_json": {
                                  "reference_schema": {
                                    "type": "chapter_verse",
                                    "pattern": "\\\\d+:\\\\d+",
                                    "fields": ["chapter", "verse"]
                                  },
                                  "relationships": {"next": ["same_chapter"], "bad": "next"},
                                  "chunking": {
                                    "unit": "verse",
                                    "include_neighbors": "1",
                                    "preserve_parallel_text": true
                                  },
                                  "retrieval": {
                                    "exact_reference_top1": true,
                                    "boost_same_chapter": "yes"
                                  }
                                }
                              },
                              "confidence": 0.86,
                              "evidence_pages": [1],
                              "rationale": "Samples show Quran references.",
                              "warnings": []
                            }"""
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
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="quran.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Surah 1 [1:1]")],
        sampler_warnings=[],
    )

    assert result.domain_metadata.custom_json == {
        "reference_schema": {"type": "chapter_verse"},
        "relationships": {"next": ["same_chapter"]},
        "chunking": {"unit": "verse", "preserve_parallel_text": True},
        "retrieval": {"exact_reference_top1": True},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_json_literal", ["null", "[]", '"bad"'])
async def test_ai_domain_metadata_suggester_prunes_invalid_custom_json_value(
    monkeypatch,
    custom_json_literal,
):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": f"""{{
                              "domain_metadata": {{
                                "domain": "quran_tafseer",
                                "document_type": "commentary",
                                "tags": ["quran"],
                                "custom_json": {custom_json_literal}
                              }},
                              "confidence": 0.86,
                              "evidence_pages": [1],
                              "rationale": "Samples show Quran references.",
                              "warnings": []
                            }}"""
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
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="quran.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Surah 1 [1:1]")],
        sampler_warnings=[],
    )

    assert result.domain_metadata.custom_json == {}


@pytest.mark.asyncio
async def test_ai_domain_metadata_prompt_includes_selected_profile_context(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "hadith",
                                "document_type": "collection",
                                "tags": ["hadith"]
                              },
                              "confidence": 0.8,
                              "evidence_pages": [1],
                              "rationale": "The sample shows hadith references.",
                              "warnings": []
                            }"""
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
            calls.append(json)
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="hadith.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Book 1, Hadith 1")],
        sampler_warnings=[],
        baseline_profile=DomainMetadata(
            domain="hadith",
            document_type="collection",
            citation_style="book_hadith",
            tags=["hadith"],
            authority="do-not-prompt-authority",
            source="do-not-prompt-source",
            collection="do-not-prompt-collection",
            metadata_sources=["do-not-prompt-source-list"],
            custom_json={
                "chunking": {"unit": "hadith"},
                "unsupported": {"large": "do-not-prompt-custom-json"},
            },
        ),
    )

    prompt = calls[0]["messages"][0]["content"][0]["text"]
    assert "Selected baseline profile metadata" in prompt
    assert '"domain": "hadith"' in prompt
    assert '"citation_style": "book_hadith"' in prompt
    assert '"chunking"' in prompt
    assert "do-not-prompt-authority" not in prompt
    assert "do-not-prompt-source" not in prompt
    assert "do-not-prompt-collection" not in prompt
    assert "do-not-prompt-source-list" not in prompt
    assert "do-not-prompt-custom-json" not in prompt


def test_ai_domain_metadata_prompt_bounds_nested_custom_json():
    oversized_value = "v" * (BASELINE_PROMPT_MAX_STRING + 25)
    too_deep_value = "too-deep-value"
    metadata = DomainMetadata.model_construct(
        domain="legal",
        document_type="code",
        language="unknown",
        tags=[
            {
                "level_1": {
                    "level_2": {
                        "level_3": {
                            "level_4": {
                                "level_5": {
                                    "level_6": too_deep_value,
                                },
                            },
                        },
                    },
                },
            }
        ],
        custom_json={
            "reference_schema": {
                "type": "section",
                "display": oversized_value,
                "fields": {
                    f"field_{index:02d}": oversized_value
                    for index in range(BASELINE_PROMPT_MAX_DICT_ITEMS + 4)
                },
            },
            "relationships": {
                f"relationship_{index:02d}": [
                    f"target_{target_index:02d}"
                    for target_index in range(BASELINE_PROMPT_MAX_LIST + 4)
                ]
                for index in range(BASELINE_PROMPT_MAX_DICT_ITEMS + 4)
            },
            "chunking": {"unit": "section", "include_neighbors": 2},
            "retrieval": {
                f"retrieval_{index:02d}": True
                for index in range(BASELINE_PROMPT_MAX_DICT_ITEMS + 4)
            },
            "graph": {
                "node_types": [
                    f"node_{index:02d}" for index in range(BASELINE_PROMPT_MAX_LIST + 4)
                ],
                "edge_types": ["contains"],
                "materialize_from": ["reference_metadata"],
                "confidence_policy": "evidence_required",
            },
        },
    )

    prompt_metadata = DomainMetadataAiSuggester()._baseline_prompt_metadata(metadata)
    prompt = json.dumps(prompt_metadata, ensure_ascii=False)

    assert '"reference_schema"' in prompt
    assert '"chunking"' in prompt
    assert '"retrieval"' in prompt
    assert '"graph"' in prompt
    assert too_deep_value not in prompt
    assert oversized_value not in prompt
    assert "v" * BASELINE_PROMPT_MAX_STRING in prompt
    assert '"field_00"' in prompt
    assert f'"field_{BASELINE_PROMPT_MAX_DICT_ITEMS - 1:02d}"' in prompt
    assert f'"field_{BASELINE_PROMPT_MAX_DICT_ITEMS:02d}"' not in prompt
    assert '"relationship_00"' in prompt
    assert f'"relationship_{BASELINE_PROMPT_MAX_DICT_ITEMS:02d}"' not in prompt
    assert f'"target_{BASELINE_PROMPT_MAX_LIST - 1:02d}"' in prompt
    assert f'"target_{BASELINE_PROMPT_MAX_LIST:02d}"' not in prompt
    assert '"retrieval_00"' in prompt
    assert f'"retrieval_{BASELINE_PROMPT_MAX_DICT_ITEMS:02d}"' not in prompt
    assert f'"node_{BASELINE_PROMPT_MAX_LIST - 1:02d}"' in prompt
    assert f'"node_{BASELINE_PROMPT_MAX_LIST:02d}"' not in prompt


def test_ai_metadata_merge_fills_empty_fields_and_unions_tags():
    suggester = DomainMetadataAiSuggester()
    baseline = DomainMetadata(
        domain="hadith",
        document_type="collection",
        language="unknown",
        tags=["hadith", "arabic"],
        metadata_sources=["profile", "baseline_supplied"],
    )
    ai = DomainMetadata(
        domain="islamic_hadith",
        document_type="hadith_collection",
        language="arabic",
        tags=["hadith", "sahih_al_bukhari"],
        collection="sahih_al_bukhari",
        metadata_sources=["ai_vision"],
    )

    merged = suggester.merge_with_baseline(ai, baseline)

    assert merged.domain == "hadith"
    assert merged.document_type == "collection"
    assert merged.language == "arabic"
    assert merged.collection == "sahih_al_bukhari"
    assert merged.tags == ["hadith", "arabic", "sahih_al_bukhari"]
    assert merged.metadata_sources == ["profile"]


def test_ai_metadata_merge_deep_merges_custom_json():
    suggester = DomainMetadataAiSuggester()
    baseline = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "fields": {"book": "book_number", "hadith": "hadith_number"},
            },
            "chunking": {"unit": "hadith", "include_neighbors": 1},
            "parser_normalization": {
                "allow_equations_as_content": False,
                "recover_text_bearing_blocks_as_prose": True,
            },
            "retrieval": {"exact_reference_top1": True},
            "graph": {
                "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
                "edge_types": ["contains", "next_hadith"],
                "materialize_from": ["mineru_structure"],
                "confidence_policy": "evidence_required",
            },
        }
    )
    ai = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "fields": {"chapter": "chapter_title"},
            },
            "chunking": {"preserve_parallel_text": True},
            "parser_normalization": {"preserve_original_block_type": True},
            "retrieval": {"boost_same_chapter": True},
            "graph": {"edge_types": ["same_chapter"]},
        }
    )

    merged = suggester.merge_with_baseline(ai, baseline)

    assert merged.custom_json == {
        "reference_schema": {
            "type": "book_hadith",
            "display": "Book {book}, Hadith {hadith}",
            "fields": {
                "book": "book_number",
                "hadith": "hadith_number",
                "chapter": "chapter_title",
            },
        },
        "chunking": {
            "unit": "hadith",
            "include_neighbors": 1,
            "preserve_parallel_text": True,
        },
        "parser_normalization": {
            "allow_equations_as_content": False,
            "recover_text_bearing_blocks_as_prose": True,
            "preserve_original_block_type": True,
        },
        "retrieval": {
            "exact_reference_top1": True,
            "boost_same_chapter": True,
        },
        "graph": {
            "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
            "edge_types": ["contains", "next_hadith", "same_chapter"],
            "materialize_from": ["mineru_structure"],
            "confidence_policy": "evidence_required",
        },
    }


def test_ai_metadata_merge_prunes_partial_graph_without_baseline():
    suggester = DomainMetadataAiSuggester()
    normalized = suggester._normalize_custom_json(
        {
            "chunking": {"unit": "paragraph"},
            "graph": {"edge_types": ["references"]},
        }
    )

    assert normalized == {"chunking": {"unit": "paragraph"}}
    validate_custom_json(normalized)


def test_ai_metadata_merge_preserves_valid_reference_patterns():
    suggester = DomainMetadataAiSuggester()
    baseline = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "legal_section",
                "pattern": r"(?P<section>\d+):(?P<clause>\d+)",
            }
        }
    )
    ai = DomainMetadata(
        custom_json={
            "reference_schema": {
                "regex": r"(?P<article>\d+)-(?P<line>\d+)",
                "fields": {"article": "article_number"},
            }
        }
    )

    merged = suggester.merge_with_baseline(ai, baseline)

    assert merged.custom_json == {
        "reference_schema": {
            "type": "legal_section",
            "pattern": r"(?P<section>\d+):(?P<clause>\d+)",
            "regex": r"(?P<article>\d+)-(?P<line>\d+)",
            "fields": {"article": "article_number"},
        }
    }
    validate_custom_json(merged.custom_json)


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_merges_baseline_and_ai_source(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "islamic_hadith",
                                "document_type": "hadith_collection",
                                "language": "arabic",
                                "tags": ["hadith", "sahih_al_bukhari"],
                                "collection": "sahih_al_bukhari",
                                "metadata_sources": ["model_supplied"]
                              },
                              "confidence": 0.88,
                              "evidence_pages": [1],
                              "rationale": "Sample page shows hadith references.",
                              "warnings": []
                            }"""
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
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="hadith.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Book 1, Hadith 1")],
        sampler_warnings=[],
        baseline_profile=DomainMetadata(
            domain="hadith",
            document_type="collection",
            tags=["hadith", "arabic"],
            metadata_sources=["profile", "baseline_supplied"],
        ),
    )

    metadata = result.domain_metadata
    assert metadata.domain == "hadith"
    assert metadata.document_type == "collection"
    assert metadata.language == "arabic"
    assert metadata.collection == "sahih_al_bukhari"
    assert metadata.tags == ["hadith", "arabic", "sahih_al_bukhari"]
    assert metadata.metadata_sources == ["profile", "ai_vision"]


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_merges_partial_graph_into_baseline(
    monkeypatch,
):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "hadith",
                                "document_type": "collection",
                                "tags": ["hadith"],
                                "custom_json": {
                                  "graph": {"edge_types": ["same_chapter"]}
                                }
                              },
                              "confidence": 0.88,
                              "evidence_pages": [1],
                              "rationale": "Sample page shows hadith references.",
                              "warnings": []
                            }"""
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
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="hadith.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Book 1, Hadith 1")],
        sampler_warnings=[],
        baseline_profile=DomainMetadata(
            domain="hadith",
            document_type="collection",
            tags=["hadith"],
            custom_json={
                "graph": {
                    "edge_types": ["references"],
                    "materialize_from": ["reference_metadata"],
                    "confidence_policy": "evidence_required",
                }
            },
        ),
    )

    assert result.domain_metadata.custom_json == {
        "graph": {
            "edge_types": ["references", "same_chapter"],
            "materialize_from": ["reference_metadata"],
            "confidence_policy": "evidence_required",
        }
    }


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_merges_meaningful_generic_baseline(
    monkeypatch,
):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "admin",
                                "document_type": "policy",
                                "language": "english",
                                "tags": ["ai-tag"],
                                "custom_json": {
                                  "chunking": {"unit": "paragraph"}
                                },
                                "metadata_sources": ["model_supplied"]
                              },
                              "confidence": 0.8,
                              "evidence_pages": [1],
                              "rationale": "Sample page shows policy text.",
                              "warnings": []
                            }"""
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
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="policy.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Policy text")],
        sampler_warnings=[],
        baseline_profile=DomainMetadata(
            domain="generic",
            document_type="document",
            tags=["document", "saved-profile"],
            expected_structure="sections",
            custom_json={"retrieval": {"exact_reference_top1": True}},
        ),
    )

    metadata = result.domain_metadata
    assert metadata.domain == "generic"
    assert metadata.document_type == "document"
    assert metadata.language == "english"
    assert metadata.tags == ["document", "saved-profile", "ai-tag"]
    assert metadata.custom_json == {
        "retrieval": {"exact_reference_top1": True},
        "chunking": {"unit": "paragraph"},
    }
    assert metadata.metadata_sources == ["profile", "ai_vision"]


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_retries_without_response_format(monkeypatch):
    calls = []

    class RejectedResponse:
        status_code = 400

        def json(self):
            return {"error": "unsupported response_format"}

    class AcceptedResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "policy",
                                "document_type": "admin_document",
                                "tags": ["policy"]
                              },
                              "confidence": 0.81,
                              "evidence_pages": [1],
                              "rationale": "The page shows policy sections.",
                              "warnings": []
                            }"""
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
            calls.append(json)
            return RejectedResponse() if len(calls) == 1 else AcceptedResponse()

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
        filename="policy.txt",
        content_type="text/plain",
        pages=[SampledPage(page_number=1, text="Policy sections")],
        sampler_warnings=[],
    )

    assert result.domain_metadata.domain == "policy"
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_does_not_retry_unrelated_bad_request(
    monkeypatch,
):
    calls = []

    class RejectedResponse:
        status_code = 400

        def json(self):
            return {"error": "model does not exist"}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            calls.append(json)
            return RejectedResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    with pytest.raises(ValueError, match="HTTP 400"):
        await DomainMetadataAiSuggester().suggest(
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
            filename="policy.txt",
            content_type="text/plain",
            pages=[SampledPage(page_number=1, text="Policy sections")],
            sampler_warnings=[],
        )

    assert len(calls) == 1
    assert "response_format" in calls[0]


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggest_endpoint_uses_vision_model(client, monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "quran_tafseer",
                                "document_type": "commentary",
                                "language": "mixed",
                                "tags": ["quran", "tafseer"],
                                "citation_style": "surah_ayah",
                                "expected_structure": "surah_ayah_sections",
                                "script": "mixed",
                                "content_role": "tafseer",
                                "metadata_sources": ["ai_vision"]
                              },
                              "confidence": 0.92,
                              "evidence_pages": [1],
                              "rationale": "Sample pages show Quran verses and commentary.",
                              "warnings": []
                            }"""
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
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="text-model",
                llm_base_url="http://llm.test/v1",
                embedding_model="embedding-model",
                storage_backend="postgres",
                vision_model="vision-model",
                vision_base_url="http://vision.test/v1",
                vision_api_key="vision-secret",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        data={"profile_id": "generic"},
        files={"file": ("tafseer.txt", b"Surah Al-Fatiha tafseer commentary", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["domain_metadata"]["domain"] == "quran_tafseer"
    assert body["domain_metadata"]["metadata_sources"] == ["ai_vision"]
    assert body["confidence"] == 0.92
    assert calls[0]["url"] == "http://vision.test/v1/chat/completions"
    assert calls[0]["headers"]["authorization"] == "Bearer vision-secret"
    assert calls[0]["json"]["model"] == "vision-model"
    assert calls[0]["json"]["temperature"] == 0


@pytest.mark.asyncio
async def test_domain_metadata_suggest_passes_selected_profile_to_suggester(
    client,
    monkeypatch,
):
    captured = {}

    async def fake_suggest(
        self,
        *,
        settings_profile,
        filename,
        content_type,
        pages,
        sampler_warnings,
        baseline_profile=None,
    ):
        captured["baseline_profile"] = baseline_profile
        return DomainMetadataSuggestOut(
            domain_metadata=baseline_profile.model_copy(
                update={"metadata_sources": ["profile", "ai_llm"]}
            ),
            confidence=0.75,
            evidence_pages=[1],
            rationale="Profile was used as baseline.",
            warnings=[],
        )

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.DomainMetadataAiSuggester.suggest",
        fake_suggest,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="vision-model",
                llm_base_url="http://llm.test/v1",
                llm_capabilities=["vision"],
                embedding_model="embedding-model",
                storage_backend="postgres",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        data={"profile_id": "hadith"},
        files={"file": ("hadith.txt", b"Book 1, Hadith 1", "text/plain")},
    )

    assert response.status_code == 200
    assert captured["baseline_profile"].domain == "hadith"
    assert response.json()["domain_metadata"]["metadata_sources"] == ["profile", "ai_llm"]


@pytest.mark.asyncio
async def test_domain_metadata_suggest_unknown_profile_returns_404(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="vision-model",
                llm_base_url="http://llm.test/v1",
                llm_capabilities=["vision"],
                embedding_model="embedding-model",
                storage_backend="postgres",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        data={"profile_id": "missing-profile"},
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Domain profile not found."


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggest_requires_default_settings(client):
    response = await client.post(
        "/api/domain-profiles/suggest",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Default settings profile is required for AI metadata autosuggest."
    )


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggest_rejects_unsupported_file_type(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="text-model",
                llm_base_url="http://llm.test/v1",
                embedding_model="embedding-model",
                storage_backend="postgres",
                vision_model="vision-model",
                vision_base_url="http://vision.test/v1",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        files={
            "file": (
                "document.docx",
                b"PK\x03\x04 fake office document",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Could not sample pages from this file for AI metadata autosuggest."
    )


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggest_rejects_oversized_upload(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="text-model",
                llm_base_url="http://llm.test/v1",
                embedding_model="embedding-model",
                storage_backend="postgres",
                vision_model="vision-model",
                vision_base_url="http://vision.test/v1",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        files={"file": ("large.txt", b"x" * (25 * 1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Upload exceeds 25 MiB limit"


@pytest.mark.asyncio
async def test_ai_domain_metadata_suggest_returns_502_for_llm_transport_error(
    client,
    monkeypatch,
):
    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="text-model",
                llm_base_url="http://llm.test/v1",
                embedding_model="embedding-model",
                storage_backend="postgres",
                vision_model="vision-model",
                vision_base_url="http://vision.test/v1",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 502
    assert "Metadata autosuggest LLM response was invalid" in response.json()["detail"]
    assert "ConnectError: connection failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_domain_metadata_suggest_does_not_use_filename_heuristics(client):
    response = await client.post(
        "/api/domain-profiles/suggest",
        json={
            "filename": "hadith_bukhari.pdf",
            "content_type": "application/pdf",
            "profile_id": "hadith",
            "sample_text": "Sahih al-Bukhari\nBook 1, Hadith 1",
        },
    )

    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_saved_domain_profile_round_trip(client):
    payload = {
        "id": "uaeu_policy",
        "name": "UAEU policy",
        "description": "Local policy profile",
        "metadata": {
            "domain": "policy",
            "document_type": "admin_document",
            "tags": ["uaeu", "policy"],
            "metadata_sources": ["user"],
        },
    }

    create_response = await client.put("/api/domain-profiles/uaeu_policy", json=payload)
    list_response = await client.get("/api/domain-profiles")

    assert create_response.status_code == 200
    assert any(item["id"] == "uaeu_policy" for item in list_response.json()["items"])


@pytest.mark.asyncio
async def test_saved_domain_profile_validates_custom_json(client):
    response = await client.put(
        "/api/domain-profiles/bad_reference",
        json={
            "id": "bad_reference",
            "name": "Bad reference",
            "metadata": {
                "domain": "legal",
                "custom_json": {"chunking": {"include_neighbors": True}},
            },
        },
    )

    assert response.status_code == 422
    assert "include_neighbors" in response.json()["detail"]


@pytest.mark.asyncio
async def test_saved_domain_profile_rejects_builtin_id(client):
    response = await client.put(
        "/api/domain-profiles/hadith",
        json={
            "id": "hadith",
            "name": "Override",
            "metadata": {"domain": "custom"},
        },
    )

    assert response.status_code == 409
