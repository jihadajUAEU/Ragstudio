# Shared Metadata-Driven Chunking Design

## Goal

Prevent Ragstudio from storing oversized single chunks from any parser, with the MinerU tafseer failure as the primary regression case.

## Problem

The completed MinerU run for `tafseer_ibn_kathir.pdf` succeeded, but Ragstudio persisted one chunk:

- Document ID: `5343f804-0af7-4d18-8aba-ccb2b090e1a5`
- Job ID: `ac92f42a-bd72-4513-a78a-341769cbd508`
- Stored chunks: `1`
- Stored chunk size: `8,323,154` characters
- Artifact: `source_1c3d8a54/source/auto/source.md`

MinerU produced rich artifacts, including page/content JSON, but `MinerUClient.normalize_artifact_zip()` currently turns each manifest text artifact into one `AdapterChunk`. The real artifact zip exposed one huge markdown file, so Ragstudio stored one huge chunk.

## Selected Approach

Use a **hybrid shared chunking layer**.

All parser outputs pass through a shared `ChunkSplitter` after adapter normalization and before database persistence. The splitter applies metadata-driven chunk profiles and a hard safety cap. For MinerU artifacts, it can also use available artifact hints such as markdown headings, page markers, and `source_content_list` files.

This is shared infrastructure, not a MinerU-only patch. MinerU gets better metadata-aware behavior first, while local fallback and runtime indexing also gain protection against oversized chunks.

## Architecture

Current flow:

```text
Parser -> AdapterChunk(s) -> ChunkService persists chunks
```

New flow:

```text
Parser -> AdapterChunk(s) -> ChunkSplitter -> ChunkService persists chunks
```

`ChunkSplitter` receives:

- Raw `AdapterChunk`s.
- `DomainMetadata`.
- Parser mode.
- Optional parser metadata, including artifact references and MinerU related artifacts.

It returns retrieval-sized `AdapterChunk`s with:

- Split text.
- Preserved source location.
- Preserved parser metadata.
- Updated `chunk_index`.
- Additional split metadata, such as parent artifact, split index, split strategy, and optional page/heading hints.

## Chunk Profiles

Chunking is driven by `domain_metadata`, with deterministic rules:

| Metadata | Strategy | Target |
| --- | --- | --- |
| `domain=tafseer` or `document_type=book` | Semantic section chunks using headings/pages when available | 800-1,200 words, hard cap 1,500 words |
| `domain=quran` or verse-heavy text | Verse-aware chunks where possible | Smaller chunks, verse plus nearby translation/commentary |
| `document_type=paper` | Section/heading chunks | 600-1,000 words |
| `document_type=table` | Table/row-block chunks | Do not blindly split by words |
| Generic metadata | Heading/paragraph chunks | 800-1,200 words, hard cap 1,500 words |

The hard cap applies to all profiles. No parser path may persist an oversized chunk.

## MinerU Artifact Handling

For MinerU output, the splitter should prefer structured hints when available:

1. If a content-list artifact exists, use page/block entries to build chunks with page metadata.
2. If only markdown exists, split by headings, page markers, verse markers, and paragraph boundaries.
3. If semantic boundaries produce chunks above the hard cap, split further by paragraph and word count.

The first implementation does not need a perfect tafseer ontology. It must reliably avoid one giant chunk and preserve enough metadata to trace chunks back to the source artifact and page/section where possible.

## Metadata Preservation

Every split chunk must retain existing parser and domain metadata.

Additional split metadata should be nested under `parser_metadata`, for example:

```json
{
  "split_strategy": "metadata_profile",
  "split_profile": "tafseer_book",
  "parent_artifact_ref": "source_1c3d8a54/source/auto/source.md",
  "parent_chunk_index": 0,
  "split_index": 12,
  "split_count": 438
}
```

If page information is available, store it in `source_location`:

```json
{
  "artifact": "source_1c3d8a54/source/auto/source.md",
  "page_start": 10,
  "page_end": 12
}
```

## Error Handling

Chunk splitting should fail closed for truly invalid data but avoid breaking successful parsing for normal text.

- Empty chunks are discarded.
- Chunks with only whitespace are discarded.
- Invalid content-list JSON falls back to markdown/text splitting.
- If a single paragraph exceeds the hard cap, split it by word count.
- If splitting fails unexpectedly in strict MinerU mode, the job should fail rather than silently storing one huge chunk.
- If splitting fails unexpectedly in fallback modes, use the existing fallback behavior only if it still respects the hard cap.

## Acceptance Criteria

The Excel-marked MinerU failure becomes a regression target:

- A synthetic MinerU artifact zip with one huge `source.md` must produce many chunks.
- No produced chunk may exceed the configured hard cap.
- The chunk count for a large tafseer-like markdown file must be greater than one.
- Split chunks retain `parser_metadata.backend=mineru`.
- Split chunks retain domain metadata.
- Split chunks include split metadata linking back to the parent artifact.
- Local fallback/runtime paths must also pass through the hard-cap protection.

## Testing

Add focused unit tests for the splitter and integration tests for MinerU normalization.

Recommended tests:

- `ChunkSplitter` splits a large markdown text into multiple chunks under the hard cap.
- `ChunkSplitter` uses `domain=tafseer` / `document_type=book` profile.
- `ChunkSplitter` preserves metadata and updates split indices.
- MinerU normalization no longer emits one chunk for a huge markdown artifact.
- Invalid MinerU content-list JSON falls back to markdown splitting.
- Existing MinerU artifact tests still pass for small text artifacts.
- ChunkService persists multiple chunks from a single oversized parser chunk.

## Out of Scope

- AI-based semantic chunking.
- Perfect verse-to-commentary alignment.
- Reprocessing all existing documents automatically.
- UI controls for chunk profile tuning.
- Changing the MinerU HPC sidecar.

