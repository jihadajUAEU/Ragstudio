# Contributing To Ragstudio

Thanks for helping improve Ragstudio. The project is still moving quickly, so small, well-scoped pull requests are easiest to review.

## Development Setup

```bash
./scripts/setup.sh
./scripts/dev.sh
```

Use Docker Compose for local development unless a maintainer asks for a narrower backend or frontend-only reproduction.

## Before Opening A Pull Request

- Keep changes focused on one behavior or documentation area.
- Add or update tests for user-visible behavior, API contracts, worker behavior, or proof packet changes.
- Run:

```bash
./scripts/test-all.sh
```

- If you change frontend API usage, regenerate types after the backend is running:

```bash
cd frontend
npm run generate:api
```

- If you change public proof packets, run the proof validator:

```bash
./scripts/proof.sh --strict --json --packet docs/benchmarks/ragstudio-oss-proof-v1
```

## Pull Request Checklist

- [ ] The change is scoped and described clearly.
- [ ] Tests or proof validation were run and documented in the PR.
- [ ] No private documents, provider keys, local database dumps, screenshots with private content, or generated caches are committed.
- [ ] Documentation is updated when behavior, configuration, or workflows change.
- [ ] Public claims are backed by proof artifacts or explicitly marked roadmap/disabled.

## Public Claims Rule

Do not turn a benchmark target, roadmap item, local-only experiment, or private run into public product copy unless a redacted proof packet exists and validates.

## Code Style

- Match existing backend service and repository patterns.
- Match existing frontend component and test patterns.
- Prefer explicit schemas and typed API boundaries over ad hoc payloads.
- Keep comments sparse and useful.

## Security Reports

Do not open public issues for vulnerabilities. Follow [SECURITY.md](SECURITY.md).
