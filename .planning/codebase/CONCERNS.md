# Codebase Concerns

**Analysis Date:** 2026-05-14

## Tech Debt

**Manual Schema Evolution:**
- Issue: `backend/src/ragstudio/db/engine.py` uses `Base.metadata.create_all()` plus `_ensure_runtime_columns()` and manual backfills instead of migration files.
- Why: Fast-moving local product runtime work needed compatibility across existing databases.
- Impact: Schema drift is easy to miss, column additions can accumulate in one large compatibility function, and release proof scripts must account for existing DB states.
- Fix approach: Introduce explicit Alembic migrations or a documented migration layer before broader public deployment.

**Large Frontend Feature Files:**
- Issue: Some pages, especially `frontend/src/features/documents/documents-page.tsx`, contain many local helpers and UI sections in one file.
- Why: Feature behavior evolved quickly around jobs, warning details, search, and repair actions.
- Impact: Edits can be hard to review and accidental UI regressions are more likely.
- Fix approach: Extract stable subcomponents once behavior settles, keeping tests at the feature boundary.

**Generated API Types Are Ignored:**
- Issue: `frontend/src/api/generated.ts` is referenced by source but ignored in `.gitignore`.
- Why: Types are generated from backend OpenAPI.
- Impact: Fresh checkouts may need generation before type-aware frontend work, and API/schema changes can drift if generation is skipped.
- Fix approach: Add a documented generation gate or commit a public-safe generated client for launch branches.

**No Repository CI Workflows Found:**
- Issue: No `.github/workflows` files were present.
- Why: Validation currently runs through local scripts.
- Impact: Public contributors and launch branches may not get automatic proof that backend/frontend tests and proof packet validation pass.
- Fix approach: Add CI for `scripts/test-all.sh` subsets plus proof-packet static validation.

## Known Bugs

**No confirmed current runtime bug from mapping alone:**
- Symptoms: None asserted by this map.
- Trigger: N/A.
- Workaround: Use live API/container checks for runtime questions, not static inspection alone.
- Root cause: N/A.

## Security Considerations

**Public Upload Demo Risk:**
- Risk: Current app accepts document uploads and can call local/private provider endpoints depending on settings.
- Current mitigation: Local dev binding, strict runtime settings, reranker host allowlist, and no auth/public hosted demo in approved launch scope.
- Recommendations: Keep V1 launch static/proof-packet based unless auth, quotas, redaction, and provider egress controls are designed.

**Provider Endpoint and Secret Handling:**
- Risk: Settings profiles include API key fields and private endpoint URLs for LLM, embeddings, vision, MinerU, reranker, Neo4j, and storage.
- Current mitigation: Settings live in local DB/env; proof-system plan requires redaction before publishing artifacts.
- Recommendations: Centralize proof export redaction and fail closed on API-key patterns, private hostnames, local IPs, and absolute local paths.

**Reranker Egress:**
- Risk: Reranker test/query paths can call external or LAN hosts.
- Current mitigation: `RAGSTUDIO_ALLOWED_RERANKER_HOSTS` and connection-service validation.
- Recommendations: Keep allowlist tests with every settings/provider-sync change.

## Performance Bottlenecks

**Heavy Runtime Image Build:**
- Problem: Backend Docker image installs full RAG-Anything/MinerU/Paddle/PyTorch stack.
- Measurement: No timing captured in this map, but dependency footprint is high.
- Cause: Native OCR/RAG runtime dependencies are installed into the backend image.
- Improvement path: Cache build layers carefully, keep constraints pinned, and consider separating proof static validation from live runtime image requirements.

**Long-Running MinerU Jobs:**
- Problem: MinerU parsing can take a long time and is network/sidecar dependent.
- Measurement: Default timeout is large; code uses async polling and worker leases.
- Cause: OCR/layout parsing and artifact download are heavy operations.
- Improvement path: Keep worker lease/heartbeat tests, expose progress, and use static-fixture proof mode for public launch validation.

**Graph Materialization:**
- Problem: Neo4j projection can be expensive on large chunk graphs.
- Measurement: No current timing captured by this map.
- Cause: Relationship/materialization work scales with chunks, references, and graph relationships.
- Improvement path: Preserve indexed `RagstudioGraphNode` lookup patterns and graph projection regression tests.

## Fragile Areas

**Runtime Profile and Settings Cross-Field Compatibility:**
- Why fragile: Runtime behavior spans DB model fields, Pydantic schemas, settings routes, settings UI, provider manifest sync, health checks, and runtime policy.
- Common failures: UI/backend field drift, missing default/backfill columns, provider test paths not matching query/index paths.
- Safe modification: Update schema/model/service/UI/tests together; run backend settings tests and frontend settings-page tests.
- Test coverage: Strong existing coverage in `backend/tests/test_settings.py`, `test_runtime_health_service.py`, and `frontend/tests/settings-page.test.tsx`.

**Indexing Pipeline:**
- Why fragile: Upload/indexing crosses artifacts, jobs, parser options, runtime readiness, MinerU, chunk persistence, quality gates, vector materialization, graph projection, and job recovery.
- Common failures: Active job conflicts, stale leases, partial graph projection, parser warning policy regressions.
- Safe modification: Add focused backend tests and inspect job result payloads, not just status codes.
- Test coverage: Broad coverage exists across documents, jobs, index lifecycle, worker recovery, quality gates, and graph materialization.

**Retrieval Orchestrator:**
- Why fragile: Query quality depends on native runtime candidates, metadata fallback, graph expansion, fusion, reranking, context assembly, and grounding.
- Common failures: Exact-reference candidates not entering retrieval, degraded native scope behavior, traces not reflecting the actual path.
- Safe modification: Preserve trace semantics and add regression tests for the query shape being changed.
- Test coverage: Strong service-level tests exist, plus selected E2E coverage.

**Frontend Manual Routing:**
- Why fragile: `App.tsx` manually maps paths to pages and `routes.ts` separately maps nav entries.
- Common failures: New page added to one map but not the other.
- Safe modification: Update both files together and add/adjust app-shell or route tests.
- Test coverage: `frontend/tests/app-shell.test.tsx` and page tests cover much of the surface.

## Scaling Limits

**Local Workbench Assumption:**
- Current capacity: Designed for local/operator use with a single Compose stack.
- Limit: No authentication, multi-tenant isolation, public upload controls, or hosted quota model.
- Symptoms at limit: Security and operational risk before pure throughput becomes the main bottleneck.
- Scaling path: Keep V1 launch static; design hosted service separately if needed.

**Synchronous Public Proof Expectations:**
- Current capacity: Static proof packets can be inspected cheaply.
- Limit: Live-capture mode depends on Docker, providers, sidecars, and private configuration.
- Symptoms at limit: Fresh checkout users cannot reproduce live artifacts.
- Scaling path: Use static-fixtures as the required release gate and live-capture as optional refresh.

## Dependencies at Risk

**Native RAG/OCR Stack:**
- Risk: `raganything`, MinerU, Paddle, Torch, and PyMuPDF versions are heavy and compatibility-sensitive.
- Impact: Image builds or runtime imports can fail on dependency drift.
- Migration plan: Keep `constraints/runtime-latest.txt`, `scripts/runtime_import_smoke.py`, and Docker build checks current.

**Frontend `latest` Dependencies:**
- Risk: Several frontend dependencies are set to `latest` in `frontend/package.json`.
- Impact: Fresh installs can drift when lockfile is regenerated.
- Migration plan: Keep `package-lock.json` committed and consider pinning public launch dependencies.

## Missing Critical Features

**Proof Packet Tooling Not Yet Implemented:**
- Problem: Approved launch plan needs replay/export schemas, manifests, claims registry, redaction, and static proof viewer import contract.
- Current workaround: Existing app has proof signals in UI/API/tests, but not a packaged public artifact.
- Blocks: Public proof-system launch.
- Implementation complexity: Medium to high, spanning backend proof module, scripts, docs, and separate site import.

**Formal Public CI Gate:**
- Problem: Launch needs automatic validation for static fixture proof packets and claims registry evidence.
- Current workaround: Local scripts and tests.
- Blocks: Credible public launch/reviewer trust.
- Implementation complexity: Medium.

## Test Coverage Gaps

**End-to-End Proof Export:**
- What's not tested: No proof packet export/import pipeline exists yet.
- Risk: Public claims could drift from artifacts without a hard gate.
- Priority: High for open-source proof launch.
- Difficulty to test: Moderate; most logic can be pure schema/hash/redaction validation.

**Hosted/Public Security Posture:**
- What's not tested: Auth, public upload abuse controls, quotas, and external egress policy for a hosted demo.
- Risk: Unsafe public deployment if scope expands beyond static site.
- Priority: High only if public hosted upload/demo returns to scope.
- Difficulty to test: High because it needs a separate product/security design.

---
*Concerns audit: 2026-05-14*
*Update as issues are fixed or new ones discovered*
