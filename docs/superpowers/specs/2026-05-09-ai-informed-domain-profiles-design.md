# AI-Informed Domain Profiles Design

## Goal

Improve every built-in domain profile with conservative, AI-informed metadata defaults,
make AI autosuggest refine the selected profile instead of ignoring it, and let
MinerU-derived structure guide relationship-aware chunking.

## Scope

This design covers the built-in domain profiles returned by
`DomainMetadataService.list_profiles()`, the `/api/domain-profiles/suggest`
autosuggest flow, and the local mirrored chunk metadata produced after MinerU
normalization. It does not add profile editing UI, profile persistence changes,
or new parser modes.

## Current Behavior

Built-in profiles are defined in
`backend/src/ragstudio/services/domain_metadata_service.py`. The Hadith and
Quran/Tafseer profiles have useful top-level fields, but no structured
`custom_json`. Other built-ins are intentionally sparse.

The frontend sends `profile_id` to `/api/domain-profiles/suggest`, but the backend
currently discards it. Autosuggest therefore classifies from the uploaded file only
and can replace profile-shaped defaults with file-specific metadata.

## Target Behavior

All built-in profiles should provide conservative defaults:

- Generic document: minimal section-style defaults.
- Research paper: academic structure, citation/section hints, and table/figure tags.
- Policy/admin document: policy/admin tags and section/article-style structure.
- Table/spreadsheet: row/table chunking hints without fake references.
- Hadith: book/hadith reference semantics and hadith-unit chunking.
- Quran/Tafseer: chapter/verse reference semantics, verse chunking, and parallel text.
- Fatwa/Fiqh: question-answer/ruling structure with topic and section hints.

Profiles that have clear structural units should also provide conservative graph
semantics. These semantics describe allowed node and edge types for chunking and
relation extraction; they do not contain document-specific nodes.

Built-ins must avoid file-specific values such as `source=hadith_bukhari.pdf`,
`collection=sahih_al_bukhari`, or `authority=al-bukhari` unless a future profile is
explicitly collection-specific.

Autosuggest should use a selected profile as baseline context:

1. The frontend sends `profile_id`.
2. The backend loads the profile metadata.
3. The AI prompt includes the selected profile as conservative baseline metadata.
4. The AI returns file-specific metadata.
5. The backend merges baseline profile metadata and AI metadata predictably.

## Merge Rules

The backend owns merging so the behavior is consistent across clients.

- Non-empty profile fields are preserved when AI returns empty or incompatible
  values.
- Empty or generic profile fields may be filled by AI when the sampled file supports
  the value.
- Tags are unioned with duplicates removed.
- `metadata_sources` records both profile and AI sources, for example
  `["profile", "ai_vision"]`.
- `custom_json` is deep-merged by section:
  - `reference_schema`: keep profile schema unless AI returns compatible fields.
  - `relationships`: union relationship keys and string lists.
  - `chunking`: merge valid keys such as `unit`, `include_neighbors`, and
    `preserve_parallel_text`.
  - `retrieval`: merge boolean retrieval hints only.
  - `graph`: merge conservative graph keys such as `node_types`, `edge_types`,
    `materialize_from`, and `confidence_policy`.
- Invalid AI `custom_json` shapes are pruned before validation.
- File-specific fields such as `source`, `authority`, and `collection` may be
  returned for the uploaded document, but are not added to built-in profiles.

## Backend Design

Add profile lookup support to `DomainMetadataService` so the autosuggest route can
resolve `profile_id` and fail clearly for unknown ids.

Extend `DomainMetadataAiSuggester.suggest()` to accept an optional
`baseline_profile`. The prompt should show the baseline metadata and instruct the
model to refine it conservatively.

Add a focused merge helper in the suggester service. The helper should be small and
testable, with no dependency on HTTP or page sampling.

Add a MinerU relationship builder after MinerU normalization and before chunk
persistence. The builder should use `DomainMetadata.custom_json.graph`,
`custom_json.relationships`, and extracted reference metadata to annotate chunks
with evidence-backed relationship data. The first implementation stores these
relationships in chunk metadata for local search, explain output, and future Neo4j
materialization; it does not write graph database records directly.

Relationship-aware chunking should keep natural units clean while preserving links
to adjacent or semantically connected units. For example, a Quran ayah chunk should
record previous/next ayah refs, and a Hadith chunk should record book/chapter/hadith
refs when evidence is present. This avoids stuffing neighbor text into every chunk
while still allowing retrieval to pull connected context.

## Frontend Design

The current frontend already sends `profile_id` when a profile is selected. No major
UI change is required. Existing summary text remains valid: it describes how the
returned metadata differs from the current form values.

## Error Handling

- Unknown `profile_id` returns `404`.
- Missing `profile_id` keeps current AI-only behavior.
- AI transport and response errors keep existing `502` behavior.
- Malformed optional custom JSON from AI is pruned; unrecoverable metadata response
  errors still return `502`.

## Testing

Backend tests should cover:

- Built-in profiles expose valid conservative `custom_json`.
- All built-in profile `custom_json` passes `validate_custom_json`.
- Hadith and Quran/Tafseer include reference semantics.
- Autosuggest route loads and passes selected profile metadata.
- Unknown `profile_id` returns `404`.
- Merge fills empty fields, unions tags, merges custom JSON, and preserves baseline
  values when AI output is weak.
- Graph custom JSON validates conservative node/edge semantics.
- MinerU relationship builder annotates reference chunks with graph relationships.
- Chunk persistence preserves MinerU relationship metadata.

Frontend tests should cover:

- Existing `profile_id` submission remains intact.
- A selected profile plus autosuggest still updates the form with returned metadata.

## Non-Goals

- Building a profile editor.
- Adding collection-specific built-ins such as Sahih al-Bukhari.
- Auto-selecting a profile after AI output.
- Changing MinerU parser behavior directly.
- Writing graph edges to Neo4j in this phase.
