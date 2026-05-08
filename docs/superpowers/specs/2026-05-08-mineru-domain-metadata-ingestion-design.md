# MinerU Domain Metadata Ingestion Design

Date: 2026-05-08
Status: Draft approved for planning

## Goal

Add a MinerU-backed document parsing path to Ragstudio that sends uploaded documents to an already running MinerU/RAG-Anything service, imports returned artifacts as chunks, and applies domain-aware metadata before extraction. The first version targets the Meeting Copilot MinerU API contract and does not submit or manage Slurm jobs.

## Non-Goals

- Do not add HPC Slurm job submission or startup controls in this phase.
- Do not replace the existing chunk search, query, experiments, or diagnostics flows.
- Do not keep parallel active local and MinerU chunk sets for the same document in the first version.
- Do not require authentication for the MinerU service in the first version.

## Reference Behavior From Meeting Copilot

Meeting Copilot uses a RAG-Anything sidecar with optional HPC MinerU coordinator mode. The useful contract for Ragstudio is:

1. Send a parse request to `POST /parse-async`.
2. Poll `GET /parse-jobs/{job_id}` until the job is ready, failed, or timed out.
3. Download `GET /parse-jobs/{job_id}/artifacts`.
4. Extract the returned artifact zip.
5. Collect text, page/source metadata, media/table references, and manifest data.
6. Import the extracted content into the local retrieval index.

Ragstudio should implement the same external contract through an isolated backend client so a later parser contract can be added without changing chunk search/query consumers.

## User Experience

### Settings

Add a `MinerU parser` section to Settings:

- Enable MinerU parser.
- Base URL, for example `http://127.0.0.1:8765`.
- Timeout and poll interval fields.
- Test connection action.
- Health/status display from the MinerU service when available.

No auth fields are required in this phase. The expected deployment is an SSH tunnel, VPN, or otherwise trusted local network endpoint.

### Upload And Index

Documents and Chunks indexing actions expose a parser selector:

- `Local fallback`
- `MinerU strict`
- `MinerU with fallback`

Before the parser runs, the user sees a domain metadata step:

1. Choose a saved profile or built-in profile.
2. Optionally click `Auto-suggest`.
3. Review/edit the resulting metadata.
4. Start upload/index.

`MinerU strict` fails the indexing job when MinerU fails. `MinerU with fallback` logs the MinerU failure, then indexes with the local fallback parser. `Local fallback` still receives the reviewed metadata before line splitting.

## Domain Metadata Pump

The metadata pump runs before extraction for every parser mode. It creates document-level metadata and copies it into each produced chunk.

Keep metadata split into two groups:

- `domain_metadata`: what the document is, provided by profile, heuristics, LLM, or user.
- `parser_metadata`: how a chunk was extracted, produced by local fallback or MinerU.

This prevents user/domain context from being mixed with parser implementation details.

### Metadata Sources

Supported metadata sources:

- `profile`: selected built-in or saved domain profile.
- `heuristic`: filename, extension, MIME type, and readable first text/pages when available.
- `llm`: optional reasoning-model enrichment when a configured reasoning endpoint exists.
- `user`: edits made in the UI.

The final chunk metadata should include provenance, for example:

```json
{
  "domain_metadata": {
    "domain": "hadith",
    "document_type": "collection",
    "language": "mixed",
    "collection": "Sahih al-Bukhari",
    "tags": ["hadith", "arabic", "english"],
    "metadata_sources": ["profile", "heuristic", "user"]
  },
  "parser_metadata": {
    "backend": "mineru",
    "parser_mode": "mineru_strict",
    "parse_job_id": "doc-123-abcdef",
    "content_type": "text",
    "page_number": 12
  }
}
```

### Built-In Profiles

Ship these built-in profiles:

- `Generic document`
- `Research paper`
- `Policy/admin document`
- `Table/spreadsheet`
- `Hadith`
- `Quran/Tafseer`
- `Fatwa/Fiqh`

For the first implementation, built-in profiles are code-defined constants. User-created saved profiles are stored as JSON in the local Ragstudio data directory, not in the database. This keeps profile editing independent from the core settings profile and avoids a migration-heavy profile manager in the first MinerU slice.

Common fields:

- `domain`
- `document_type`
- `language`
- `tags`
- `authority` or `source`
- `collection`
- `citation_style`
- `expected_structure`
- `custom_json`

Islamic corpus profiles allow additional structured hints:

- `collection`, such as `Sahih al-Bukhari` or `Jami at-Tirmidhi`
- `reference_pattern`, such as `Book N, Hadith N`
- `script`, such as `arabic`, `english`, or `mixed`
- `content_role`, such as `hadith`, `tafseer`, `fatwa`, or `fiqh ruling`

## Backend Design

### Settings Schema

Extend the default settings profile with MinerU connection fields:

- `mineru_enabled`
- `mineru_base_url`
- `mineru_timeout_ms`
- `mineru_poll_interval_ms`

Add a connection test endpoint, for example:

- `POST /api/settings/default/test-mineru`

The test calls `GET /health` on the configured base URL. If the service does not expose `/health`, Ragstudio reports a clear connection-test failure rather than guessing from another endpoint.

### Parser Client

Create an isolated MinerU client/service responsible for the Meeting Copilot contract:

- Submit parse job.
- Poll job status.
- Download artifact zip.
- Validate artifact paths before extraction.
- Read artifact manifest if present.
- Collect extracted text, tables, image captions, equations, page ranges, and media references.

The client returns normalized parser chunks, not database rows.

### Chunk Indexing

Extend `ChunkService.index_document` to accept:

- parser mode
- reviewed domain metadata

Indexing behavior:

- Delete existing active chunks for the document before storing new chunks.
- For local fallback, line-split as today, but copy `domain_metadata` onto every chunk.
- For MinerU, submit/poll/download/extract artifacts, then create chunks with both `domain_metadata` and `parser_metadata`.
- For MinerU with fallback, if MinerU fails, create local chunks and include parser metadata that records the MinerU failure reason and fallback use.

The `chunks` table remains the source of truth for search, query, experiments, and comparisons.

### Artifact Storage

Store MinerU artifacts under:

`.ragstudio/mineru-artifacts/<document_id>/`

Use subdirectories for:

- downloaded zip
- extracted files
- manifest
- media files

Do not expose absolute local file paths in chunk metadata. Store safe relative artifact references only.

## Frontend Design

### Settings Page

Add a `MinerU parser` section below Embeddings:

- Enable toggle.
- Base URL input.
- Timeout and poll interval numeric inputs.
- Test connection button with success/error detail.

### Upload/Index UI

Add compact parser controls where indexing starts:

- On document upload.
- On Chunks page `Index` action.

For first implementation, a simple modal or inline panel is enough:

- Parser mode selector.
- Domain profile selector.
- `Auto-suggest` button.
- Editable metadata form.
- Advanced JSON metadata textarea.
- Start button.

The UI should show which parser produced the active chunks and whether fallback was used.

### Chunk Inspector

Chunk cards should surface provenance without overwhelming the page:

- Parser backend badge: `fallback` or `mineru`.
- Domain badge, such as `hadith`, `research`, or `policy`.
- Page/source metadata when present.
- Collapsible JSON for full domain and parser metadata.
- Artifact/media/table refs when present.

## Error Handling

- Missing MinerU base URL with MinerU selected: block before job starts.
- MinerU submit failure:
  - strict mode: job failed with the service error.
  - fallback mode: job logs failure and indexes locally.
- Poll timeout:
  - strict mode: job failed with timeout detail.
  - fallback mode: job logs timeout and indexes locally.
- Artifact download or unsafe zip path:
  - always reject unsafe artifact paths.
  - strict mode fails.
  - fallback mode indexes locally and records the rejection reason.
- Invalid custom metadata JSON: block in UI before job starts.

## Testing

Backend tests:

- Settings round trip includes MinerU fields.
- MinerU connection test validates base URL behavior.
- Fake MinerU service verifies submit, poll, artifact download, and chunk import.
- Strict mode fails when MinerU fails.
- Fallback mode indexes locally and records the MinerU error.
- Domain metadata is copied to local fallback chunks.
- Domain metadata is copied to MinerU chunks.
- Unsafe artifact zip entries are rejected.

Frontend tests:

- Settings renders MinerU fields and test action states.
- Upload/index UI exposes parser mode and domain metadata review.
- Built-in profiles populate expected metadata fields.
- Chunk cards show parser/domain badges.

End-to-end QA:

- Configure `http://127.0.0.1:8765`.
- Upload a PDF with `MinerU strict`.
- Confirm chunks are created with MinerU metadata.
- Upload/index with `MinerU with fallback` against a failing fake service.
- Confirm fallback chunks are created with domain metadata and failure provenance.

## Success Criteria

- A user can connect Ragstudio to an already running MinerU service.
- A user can choose local fallback, MinerU strict, or MinerU with fallback for upload/index.
- Domain metadata is reviewed before extraction and appears on every resulting chunk.
- MinerU artifacts are downloaded, safely extracted, and normalized into Ragstudio chunks.
- Existing search, query, experiments, and diagnostics continue to work through the chunks table.
- The first version does not require Slurm orchestration inside Ragstudio.
