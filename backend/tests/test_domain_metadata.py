import pytest


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
async def test_domain_metadata_suggestion_uses_filename_and_profile(client):
    response = await client.post(
        "/api/domain-profiles/suggest",
        json={
            "filename": "hadith_bukhari.pdf",
            "content_type": "application/pdf",
            "profile_id": "hadith",
            "sample_text": "Sahih al-Bukhari\nBook 1, Hadith 1",
        },
    )

    assert response.status_code == 200
    metadata = response.json()["domain_metadata"]
    assert metadata["domain"] == "hadith"
    assert metadata["document_type"] == "collection"
    assert metadata["collection"] == "Sahih al-Bukhari"
    assert "profile" in metadata["metadata_sources"]
    assert "heuristic" in metadata["metadata_sources"]


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
