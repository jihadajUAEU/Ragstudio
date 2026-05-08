# RAG-Anything Studio

Standalone local Studio for RAG-Anything. The app provides document upload, pipeline tuning, chunk inspection, query runs, variant comparison, evaluation imports, scoring, optimizer recommendations, graph inspection, and diagnostics.

## Development

Install backend and frontend dependencies first:

```bash
docker compose up -d postgres neo4j
./scripts/setup.sh
```

The backend setup installs `raganything[all]`. If you skip setup, Studio still runs
with a local fallback adapter and the Diagnostics page will show a warning.
Runtime mode currently lands the store/profile/health/index/query foundation; the
native RAG-Anything adapter remains blocked in Diagnostics until implemented.

```bash
./scripts/dev.sh
```

## Test

```bash
./scripts/test-all.sh
```
