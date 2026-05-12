import pytest


@pytest.mark.asyncio
async def test_jobs_openapi_uses_typed_job_page(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    openapi = response.json()
    response_schema = openapi["paths"]["/api/jobs"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/JobPage"}
    job_properties = openapi["components"]["schemas"]["JobOut"]["properties"]
    for field in (
        "worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "attempts",
        "max_attempts",
        "recovery_action",
    ):
        assert field in job_properties
