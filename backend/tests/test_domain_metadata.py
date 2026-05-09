import pytest

from ragstudio.db.models import SettingsProfile
from ragstudio.services.domain_metadata_ai_suggester import DomainMetadataAiSuggester
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
    assert calls[0]["json"]["messages"][0]["content"][1]["type"] == "image_url"


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
