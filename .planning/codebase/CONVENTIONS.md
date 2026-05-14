# Coding Conventions

**Analysis Date:** 2026-05-14

## Naming Patterns

**Files:**
- Backend Python modules use snake_case, for example `runtime_health_service.py`.
- Backend tests use `test_*.py`.
- Frontend feature files use kebab-case, for example `documents-page.tsx`.
- Shared React components use kebab-case filenames with PascalCase exported functions.

**Functions and Classes:**
- Python functions/methods use snake_case.
- Python classes use PascalCase and service classes are usually named `{Domain}Service`.
- TypeScript functions and variables use camelCase.
- React components use PascalCase function exports.

**Variables and Constants:**
- Python constants use UPPER_SNAKE_CASE, for example `DEFAULT_PARSER_MODE`.
- TypeScript constants use camelCase for local values and UPPER_SNAKE_CASE only when representing fixed global values.
- IDs and payload keys generally mirror API schema field names.

**Types:**
- Pydantic models use PascalCase with suffixes like `In`, `Out`, `Page`, or `Profile`.
- TypeScript relies heavily on OpenAPI-generated types imported from `frontend/src/api/generated.ts`.

## Code Style

**Python Formatting:**
- Ruff configured in root `pyproject.toml`.
- Line length is 100.
- Target Python version is 3.12.
- Ruff lint selects `E`, `F`, `I`, `B`, `UP`, and `RUF`, with FastAPI `Depends(...)` defaults intentionally ignored through `B008`.

**Python Typing:**
- Pyright is configured in root `pyproject.toml`.
- Type checking mode is `basic`.
- Backend source is included; backend tests are excluded.

**TypeScript Formatting:**
- ESLint flat config in `frontend/eslint.config.js`.
- React Hooks rules are enabled.
- No separate Prettier config was found; follow existing file style.

## Import Organization

**Python:**
1. Future imports where needed.
2. Standard library imports.
3. Third-party imports.
4. Local `ragstudio` imports.

Examples are visible in `document_service.py`, `query_service.py`, and `retrieval_orchestrator.py`.

**TypeScript:**
1. React and package imports.
2. Type imports.
3. Internal relative imports.

Examples are visible in `frontend/src/App.tsx`, `frontend/src/features/query/query-page.tsx`, and `frontend/src/api/client.ts`.

**Path Aliases:**
- No TypeScript source alias is configured in `frontend/tsconfig.json`; imports use relative paths.
- Python package import root is `ragstudio`.

## Error Handling

**Backend Patterns:**
- API routes catch expected service errors and raise `HTTPException`.
- Services raise domain-specific errors where useful, for example `ActiveIndexJobError`, `RuntimeUnavailableError`, and `QueryResourceNotFoundError`.
- Long-running worker errors are caught, logged, and translated into failed job state.
- Query failures are often persisted on `Run` rows with `error` and `error_type` rather than raised to the client.

**Frontend Patterns:**
- `ApiError` in `frontend/src/api/client.ts` normalizes failed API responses.
- Feature pages use TanStack Query and mutation state to show loading/error UI locally.
- API invalidation happens through `useQueryClient()` after mutations.

## Logging

**Backend:**
- Logging is configured by `configure_logging()` during app creation.
- Worker logs exceptions with worker ID and job ID in `index_worker.py`.
- Job-level user-visible logs are persisted in `Job.logs`.

**Frontend:**
- No dedicated logging framework was found.
- UI state and API errors are displayed through page components.

## Comments

**General Pattern:**
- Comments are sparse and usually explain policy or exceptional behavior.
- Examples include lint-ignore rationale in `pyproject.toml` and dependency/runtime notes in `backend/Dockerfile`.
- Prefer comments for why a safety gate exists, not for restating simple code.

## Function Design

**Backend:**
- Service classes group domain behavior and accept dependencies in constructors.
- Async functions dominate API, DB, provider, and runtime paths.
- Helper functions often live below route/service methods in the same file.
- Pydantic validation and SQLAlchemy persistence are kept close to service boundaries.

**Frontend:**
- Feature pages are large but internally organized with local helper components.
- Components are function components.
- State is local React state plus TanStack Query for server state.
- Shared primitives are intentionally small: `Button`, `DataTable`, `EmptyState`, `StatusBadge`.

## Module Design

**Backend:**
- New user-visible behavior usually spans schemas, routes, services, tests, and sometimes DB model/column compatibility updates.
- Runtime configuration changes often require updates in `models.py`, `engine.py`, `schemas/settings.py`, settings service, connection tests, and frontend settings UI.
- Storage compatibility is handled by `init_db()` plus `_ensure_runtime_columns()` rather than migration files.

**Frontend:**
- `frontend/src/App.tsx` owns path selection and page mounting.
- `frontend/src/lib/routes.ts` owns nav metadata.
- `frontend/src/api/client.ts` is the single API call surface.
- Feature pages tend to own their specific presentational helpers.

---
*Convention analysis: 2026-05-14*
*Update when patterns change*
