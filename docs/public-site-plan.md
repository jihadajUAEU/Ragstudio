# Public Site Plan

The public site should stay separate from the application repo and deploy through Cloudflare Pages.

## Domain

Preferred domain: `ragstudio.dev`.

Fallback candidates:

- `rag-anything-studio.dev`
- `openragstudio.com`

## Site Structure

- `/` - product homepage and proof-first launch story.
- `/docs` - documentation index and guides.
- `/examples` - sample workflows, retrieval traces, and approved screenshots.
- `/architecture` - system diagrams and component descriptions.
- `/changelog` - release notes generated from tags/releases.
- `/github` - redirect to the GitHub repository.

## Documentation Engine

Use Docusaurus when the docs surface expands to versioned guides, API reference, examples, and architecture pages. The current static Pages site can keep serving the proof viewer while Docusaurus is introduced behind the same Cloudflare Pages project or a docs subdirectory.

## Generated Sources

- API reference: FastAPI OpenAPI from `/openapi.json`.
- Settings/config reference: backend schemas and `.env.example`.
- Screenshots: Playwright-approved captures only.
- Changelog: Git tags/releases.
- Proof claims: validated proof packet under `docs/benchmarks/`.

## Release Gate

Cloudflare Pages should deploy from `main`, provide PR previews, and block merges when docs/site checks fail.
