# Hardcoded Policy Inventory

Ragstudio keeps product runtime defaults, retrieval policy, prompts, and public-safety
redaction rules in named modules so behavior can be inspected and tested before tuning.

## Standard Defaults

- Runtime defaults live in `backend/src/ragstudio/services/runtime_defaults.py`.
- Retrieval scoring defaults live in `backend/src/ragstudio/services/retrieval_policy.py`.
- Prompt identifiers and versions live in `backend/src/ragstudio/services/prompt_templates.py`.
- Public-safety redaction rules live in `backend/src/ragstudio/services/redaction_registry.py`.
- Operational limits and eval weights live in `backend/src/ragstudio/services/operational_policy.py`.
- Built-in script/query utility regexes live in `backend/src/ragstudio/services/reference_regex_registry.py`.
- Remaining protocol constants and product policies are classified in `backend/src/ragstudio/services/static_policy_catalog.py`.

## Design Rules

- Changing a retrieval score requires a focused test that asserts ordering and trace metadata.
- Changing prompt wording requires a prompt version update and a test for the required output contract.
- Changing redaction rules requires proof-packet and document-evidence safety tests.
- Frontend runtime defaults should come from `/api/defaults`; local values are offline fallbacks only.

## Reference Contract Proof Boundary

- `reference_schema` and `domain_structure` are metadata-only reference hints until an executable contract is verified.
- Verified executable reference contracts require model-declared `identity.fields`, matching regex named groups, a valid `canonical_ref_template`, and successful execution on sampled pages.
- Generic retrieval and scoring code must consume verified contract capability, canonical references, identity ranges, and neighbor references. Domain-specific names such as `chapter`, `verse`, `surah`, and `ayah` belong in adapter fixtures or display adapters.
- There is no legacy reference-regex fallback. Enforceable document reference contracts must be model-declared, sample-executed, verified, and stored on the document before reference-unit chunking, exact reference prefiltering, or reference hypothesis normalization can use them.
- Built-in domain profiles may carry parser/layout preferences, but they must not ship executable reference schemas, reference graph edges, or domain-specific query/reference fallbacks.
- Stage-flow UI metadata is backend-owned. React may provide fallback icons, but it must not be the source of truth for pipeline stage vocabulary.

## Regex Classification Rules

- Contract execution regexes are allowed only when they are compiled from a verified document reference contract. They must come from model- or user-declared contract fields, pass custom JSON validation, execute successfully on sample pages, and be stored on the document.
- Safety and syntax regexes are standard protocol, not retrieval policy. Examples include `SAFE_REFERENCE_PATTERN`, redaction rules, path/URL detectors, and unsupported-regex-token guards.
- Script, language, whitespace, and text-cleanup regexes are standard utilities. They may be shared when they do not infer a document reference identity.
- Query-intent regexes are heuristics. They are allowed only when they classify the query or extract non-reference terms, and they should remain traceable and eval-gated when they affect ranking.
- Hardcoded reference fallback regexes are not allowed. Any generic production regex that recognizes domain reference shapes such as `number:number`, Surah/Ayah, book/hadith, legal sections, page-line anchors, or named identity fields must be replaced by verified contract execution or moved to tests/fixtures.

Use this scan pattern when reviewing drift:

```powershell
rg -n -- "Verse\\s+|Surah\\s+|Hadith\\s+|Book\\s+|\\d+\\s*:\\s*\\d+|chapter_verse|surah_ayah|book_hadith|same_chapter|next_ayah|same_surah" backend/src/ragstudio/services backend/src/ragstudio/schemas backend/src/ragstudio/domain_profiles
```

Expected non-fallback buckets after the current cleanup:

- `metadata_json_schema.py`: validation allowlists and example payloads.
- `reference_metadata.py`, `reference_contract_validator.py`, `reference_contract_execution.py`, and `reference_query_parser.py`: compilation or execution of verified document contracts.
- `reference_regex_registry.py`, `arabic_text.py`, and `script_detection.py`: script and query utility regexes.
- `hybrid_chunk_search.py` and `query_hypothesis_service.py`: query-intent and term extraction heuristics, not reference contract enforcement.

## Three-Pillar Drift Boundary

- Domain-aware behavior is generic by default. Domain-shaped names such as Quran, Surah, Ayah, Hadith, Bukhari, chapter-verse, and book-hadith belong in adapter-owned files or fixtures, not generic orchestration, scoring, query, or schema surfaces.
- Layout-aware behavior is contract-driven. Same-page and reading-order expansion are safe defaults, while bbox overlap, table-caption, figure-caption, equation, and multi-column behavior require backend layout policy evidence.
- Context-aware behavior is structural. Parent, previous, next, heading path, section path, and verified reference range links are context signals; raw semantic proximity alone is not sufficient proof of context.
- Native runtime candidates must either hydrate to canonical chunks or carry visible layout/context loss flags.
- UI trace components render backend-owned three-pillar reasons and must not invent pipeline stage vocabulary.

## Remaining Tunable Areas

- Domain-specific lexical adapters should own corpus-specific synonyms. Reference extraction behavior belongs in verified per-document contracts, not global built-ins.
- Layout proximity and chunking thresholds should become domain-profile options when eval coverage exists.
- Evaluation scoring should keep the current substring scorer as a baseline and add rubric-specific adapters separately.
- Model- or user-provided custom regexes must remain validated by document/reference contract compilers, executed on samples, and stored on the document; they must not be promoted to global built-ins.
- Proof packet IDs, proof error codes, provider manifest vocabulary, query-hypothesis vocabularies, and block-type vocabularies are protocol constants. Do not tune them like scoring weights.
