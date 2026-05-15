# Ragstudio

Ragstudio is an open-source RAG data-quality workbench for inspecting document quality before bad chunks become bad answers.

It gives RAG engineers and AI product teams a local Studio for document upload, parser warnings, chunk inspection, query runs, retrieval traces, graph inspection, reranker behavior, evaluation imports, scoring, optimizer recommendations, and diagnostics.

## Why It Exists

Most RAG failures start before the final answer: a parser misses a reference, a chunk loses context, graph projection is incomplete, or reranking hides a weak candidate. Ragstudio makes those stages visible so teams can review the evidence path instead of debugging from final answers alone.

## Current Capabilities

- Upload and inspect documents through a local Studio UI.
- Tune indexing and parsing pipelines before materialization.
- Inspect chunks, parser warnings, reference metadata, and quality gates.
- Run queries with retrieval traces, source chunks, and answer evidence.
- Compare variants, imported evaluations, scoring runs, and optimizer recommendations.
- Inspect graph projection and graph workspace state.
- Export proof packets for public claims and static proof viewers.

## Quick Start

Docker Compose is the primary supported local path.

```bash
git clone https://github.com/jihadajUAEU/Ragstudio.git
cd Ragstudio
./scripts/setup.sh
./scripts/dev.sh
```

The stack starts:

- Frontend: <http://127.0.0.1:5173>
- Backend API: <http://127.0.0.1:8000>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>
- Postgres/PGVector: `127.0.0.1:55432`
- Neo4j browser: <http://127.0.0.1:57474>
- Neo4j Bolt: `bolt://127.0.0.1:57687`

Docker Desktop or a compatible Docker Engine must be installed and running. The setup builds the backend and frontend images, including the native RAG-Anything/MinerU dependency set.

## Demo Workflow

1. Open the Studio at <http://127.0.0.1:5173>.
2. Upload a sample document.
3. Review the pipeline and parser warnings.
4. Inspect produced chunks and quality policies.
5. Run a query and open the retrieval trace.
6. Check graph and reranker evidence where configured.
7. Use evaluations, comparison, variants, and optimizer pages to review answer quality.

See the [User Guide](docs/user-guide.md) for the full walkthrough.

## Architecture

Ragstudio is split into:

- `frontend/` - Vite React Studio UI.
- `backend/` - FastAPI backend, services, schemas, workers, and persistence logic.
- `postgres` - durable application state plus PGVector-backed retrieval storage.
- `neo4j` - graph workspace and relationship inspection.
- `scripts/` - local setup, testing, proof, and release helper scripts.
- `docs/benchmarks/` - public proof packets and release artifacts.

More detail:

- [Durable RAG indexing](docs/architecture/durable-rag-indexing.md)
- [Workflows](docs/workflows.md)
- [Evaluation and experiments guide](docs/evaluation-experiments-guide.md)

## Public Site And Proof Viewer

The public website lives in a separate repository:

- Site repo: <https://github.com/jihadajUAEU/ragstudio-site>
- Public site: <https://ragstudio-site.pages.dev>

The site is intentionally static for v1. Public upload, auth, live backend calls, and provider calls are disabled until abuse, quota, cost, egress, deletion, and security controls exist.

## Development

Install dependencies and build local images:

```bash
./scripts/setup.sh
```

Run the full local stack:

```bash
./scripts/dev.sh
```

Run tests:

```bash
./scripts/test-all.sh
```

Generate frontend API types after the backend is running:

```bash
cd frontend
npm run generate:api
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

Please report vulnerabilities using the process in [SECURITY.md](SECURITY.md). Do not open public issues for private security reports.

## License

Apache License 2.0. See [LICENSE](LICENSE).
