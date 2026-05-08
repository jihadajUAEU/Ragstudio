# RAG-Anything Studio

Standalone local Studio for RAG-Anything. The app provides document upload, pipeline tuning, chunk inspection, query runs, variant comparison, evaluation imports, scoring, optimizer recommendations, graph inspection, and diagnostics.

## Development

Install backend and frontend dependencies first:

```bash
./scripts/setup.sh
```

The backend setup installs `raganything[text]`. If you skip setup, Studio still runs
with a local fallback adapter and the Diagnostics page will show a warning.

```bash
./scripts/dev.sh
```

## Test

```bash
./scripts/test-all.sh
```
