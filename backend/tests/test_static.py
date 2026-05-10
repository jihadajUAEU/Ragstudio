import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from ragstudio.static import mount_frontend


@pytest.mark.asyncio
async def test_static_serving_falls_back_to_index_for_spa_routes(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><main>Studio</main>", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    mount_frontend(app, dist)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        spa_response = await client.get("/query")
        api_response = await client.get("/api/health")
        missing_api_response = await client.get("/api/missing")
        missing_api_post_response = await client.post("/api/missing")
        openapi_response = await client.get("/openapi.json")

    assert spa_response.status_code == 200
    assert "Studio" in spa_response.text
    assert api_response.status_code == 200
    assert api_response.json() == {"status": "ok"}
    assert missing_api_response.status_code == 404
    assert missing_api_post_response.status_code == 404
    assert openapi_response.status_code == 200
