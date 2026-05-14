# Testing Patterns

**Analysis Date:** 2026-05-14

## Test Framework

**Backend Runner:**
- pytest with pytest-asyncio.
- Backend tests live under `backend/tests`.
- Shared async fixtures live in `backend/tests/conftest.py`.

**Frontend Runner:**
- Vitest with jsdom.
- Testing Library and jest-dom are installed for React component tests.
- Frontend tests live under `frontend/tests`.

**E2E Runner:**
- Playwright tests live under `e2e`.
- `e2e/playwright.config.ts` starts the frontend dev server from `frontend/`.

**Run Commands:**
```bash
./scripts/test-all.sh
docker compose run --rm backend python -m pytest backend/tests -q
docker compose run --rm backend python -m ruff check backend/src backend/tests
docker compose run --rm backend python -m pyright
cd frontend && npm run lint
cd frontend && npm run test -- --run
cd frontend && npm run build
cd frontend && npm run e2e
```

## Test File Organization

**Backend:**
```text
backend/tests/
|-- conftest.py
|-- test_documents.py
|-- test_query_runs.py
|-- test_retrieval_orchestrator.py
|-- test_settings.py
`-- test_*.py
```

**Frontend:**
```text
frontend/tests/
|-- api-client.test.ts
|-- documents-page.test.tsx
|-- query-page.test.tsx
|-- settings-page.test.tsx
`-- *-page.test.tsx
```

**E2E:**
```text
e2e/
|-- playwright.config.ts
|-- studio.spec.ts
`-- arabic-hanana-query.spec.ts
```

## Test Structure

**Backend Patterns:**
- Async tests use pytest-asyncio fixtures.
- `client` fixture builds an ASGI app with `create_app(data_dir=tmp_path, database_url=...)`.
- Each backend test database is created dynamically in PostgreSQL and dropped after the fixture.
- Tests assert API status codes, persisted rows, service outputs, and failure detail strings.

**Frontend Patterns:**
- Tests render feature pages/components with mocked API behavior or query state.
- Assertions use Testing Library queries and user-visible text/controls.
- Feature tests are named after the page they exercise.

**E2E Patterns:**
- Playwright config defaults to `http://127.0.0.1:5173`.
- Existing server reuse is enabled outside CI.
- E2E is useful for end-to-end UI flows but does not replace backend API/service tests.

## Mocking

**Backend:**
- Prefer dependency injection over broad monkeypatching when services accept adapters/factories.
- Query/runtime tests can inject fake runtime factories, health services, reranker services, or retrieval orchestrators.
- Database-backed behavior usually uses a real PostgreSQL test database.

**Frontend:**
- Mock API calls through `apiClient` seams or controlled test data.
- React Query tests should isolate query cache state per test when needed.
- Browser APIs like `window.history` are used directly by the app and may need setup in route tests.

## Fixtures and Factories

**Backend:**
- `backend/tests/conftest.py` provides `database_url`, `client`, and `reindex_document`.
- Tests often construct Pydantic payloads or DB model rows directly.
- Uploaded file tests use in-memory file payloads through `httpx.AsyncClient`.

**Frontend:**
- Test data is generally local to each test file.
- Generated API types provide the expected object shape.

## Coverage

**Requirements:**
- No numeric coverage threshold was found.
- Coverage is breadth-oriented: backend has tests for API health, documents, jobs, runtime, retrieval, graph, settings, parser quality, evaluation, optimizer, and more.
- Frontend has tests for nearly every feature page.

**Configuration:**
- Backend coverage tooling is not configured in the mapped files.
- Vitest can report coverage if configured later, but no current coverage script exists in `frontend/package.json`.

## Test Types

**Unit Tests:**
- Pure services such as `retrieval_fusion`, `context_assembly_service`, `runtime_policy`, and parser/quality helpers are tested directly.

**Integration Tests:**
- Backend API tests use real app lifespan and real PostgreSQL test databases.
- Runtime readiness and index lifecycle tests cover multi-service behavior.

**Frontend Component Tests:**
- Feature pages and shared components are tested with Vitest/Testing Library.

**E2E Tests:**
- `e2e/studio.spec.ts` and `e2e/arabic-hanana-query.spec.ts` exercise browser-visible flows.

## Common Patterns

**Async Backend Test:**
```python
async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
```

**API Error Test:**
```python
response = await client.post("/api/query", json=payload)
assert response.status_code == 404
assert "not found" in response.text
```

**Frontend Query Test:**
```typescript
render(<DocumentsPage />);
expect(await screen.findByText(/Documents/i)).toBeInTheDocument();
```

## Known Test Constraints

- Backend tests require PostgreSQL; they intentionally fail fast if the database cannot be reached.
- `./scripts/test-all.sh` requires Docker and builds images before validation.
- Frontend validation from the repo root fails because there is no root-level frontend package; run frontend commands from `frontend/`.
- Generated `frontend/src/api/generated.ts` is ignored and may need regeneration before frontend API-type changes.

---
*Testing analysis: 2026-05-14*
*Update when test patterns change*
