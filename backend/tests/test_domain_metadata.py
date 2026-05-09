import pytest
import httpx

from ragstudio.db.models import SettingsProfile
from ragstudio.services.domain_metadata_ai_suggester import DomainMetadataAiSuggester
from ragstudio.services.metadata_json_schema import validate_custom_json
from ragstudio.services.page_sampler import SampledPage


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
        },
        "retrieval": {
            "exact_reference_top1": True,
            "boost_same_chapter": True,
            "boost_neighbor_verses": True,
        },
    }

    assert validate_custom_json(custom_json) is custom_json


def test_validate_custom_json_rejects_invalid_include_neighbors_boolean():
    with pytest.raises(ValueError, match="include_neighbors"):
        validate_custom_json({"chunking": {"include_neighbors": True}})


def test_validate_custom_json_rejects_invalid_retrieval_booleans():
    with pytest.raises(ValueError, match="retrieval values must be booleans"):
        validate_custom_json({"retrieval": {"exact_reference_top1": "true"}})

    with pytest.raises(ValueError, match="retrieval values must be booleans"):
        validate_custom_json({"retrieval": {"boost_same_chapter": 1}})


def test_validate_custom_json_rejects_invalid_reference_regex():
    with pytest.raises(ValueError, match="valid regex"):
        validate_custom_json({"reference_schema": {"type": "legal_section", "pattern": "(?P<section>"}})


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
