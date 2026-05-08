# RAG-Anything Studio

Standalone local Studio for RAG-Anything. The app provides document upload, pipeline tuning, chunk inspection, query runs, variant comparison, evaluation imports, scoring, optimizer recommendations, graph inspection, and diagnostics.

## Development

Install backend and frontend dependencies first:

```bash
./scripts/setup.sh
```

Docker Desktop must be installed and running. The setup builds the backend and
frontend images, including the full native RAG-Anything/MinerU dependency set.
The backend image pins the latest supported runtime targets and patches the
PaddleX wheel metadata at build time so `PyYAML` can remain on the latest
declared version.

```bash
./scripts/dev.sh
```

The dev command starts the full stack with Docker Compose:

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:8000
- Postgres/PGVector: 127.0.0.1:55432
- Neo4j: 127.0.0.1:57474 and bolt://127.0.0.1:57687

## Test

```bash
./scripts/test-all.sh
```
