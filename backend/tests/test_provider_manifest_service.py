import httpx
import pytest
from ragstudio.services.provider_manifest_service import ProviderManifestService


class FakeManifestClient:
    def __init__(self):
        self.requests = []

    async def get(self, url):
        self.requests.append(url)
        return httpx.Response(
            200,
            json={
                "version": 1,
                "updatedAt": "2026-05-22T00:00:00Z",
                "reasoning": {
                    "apiUrl": "http://127.0.0.1:8004/v1",
                    "model": "qwen",
                },
            },
        )


class FakeProvider:
    def __init__(self):
        self.client_instance = FakeManifestClient()
        self.requests = []

    def client(self, name, *, timeout=30.0):
        self.requests.append({"name": name, "timeout": timeout})
        return self.client_instance


@pytest.mark.asyncio
async def test_provider_manifest_service_uses_http_client_provider():
    provider = FakeProvider()

    result = await ProviderManifestService(http_client_provider=provider).preview(
        "http://providers.local/manifest.json",
        current=None,
        timeout_s=4.0,
    )

    assert result.ok is True
    assert result.manifest_version == 1
    assert provider.requests == [{"name": "provider-manifest", "timeout": 4.0}]
    assert provider.client_instance.requests == ["http://providers.local/manifest.json"]
