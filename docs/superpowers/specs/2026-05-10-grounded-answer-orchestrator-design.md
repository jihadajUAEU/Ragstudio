# Grounded Answer Orchestrator Design

## Purpose

Upgrade Ragstudio's answering path from a mostly text-scoring pipeline into a grounded answer orchestrator that understands query intent, retrieves a broad evidence pool, reranks evidence, composes an answer, and validates that the final answer is supported by cited sources.

The immediate motivation is the class of failures seen in the Quran document:

- The correct chunk exists, but the evidence pool excludes it because query wording adds noise.
- The model knows the likely answer from prior knowledge, but cannot cite it because retrieval missed it.
- Small scoring patches fix individual examples but do not create a reusable architecture.

The goal is to improve answer quality while keeping retrieval auditable and measurable.

## Scope

This design covers the backend answering pipeline used by `QueryService` and `RetrievalOrchestrator`.

In scope:

- Query understanding before retrieval.
- Multi-pass candidate retrieval.
- Candidate fusion and deduplication.
- Reranker integration with a better candidate pool.
- Answer composition from grounded evidence.
- Grounding validation after answer generation.
- Trace and timing outputs for debugging.
- Evaluation gates for known retrieval/grounding failures.

Out of scope for this phase:

- Rebuilding the full Experiments or Optimizer product UI.
- Replacing the existing `RerankerService`.
- Replacing the existing `RuntimeAnswerService` wholesale.
- Full native LightRAG graph extraction performance work.
- A large redesign of indexing.

## Current Architecture

The current flow is:

```text
QueryService
  -> RetrievalOrchestrator.query()
     -> plan_for_query()
     -> native retrieval and/or metadata retrieval
     -> fuse_candidates()
     -> graph expansion
     -> fuse_candidates()
     -> optional RerankerService.rerank()
     -> RuntimeAnswerService.answer()
```

Important existing files:

- `backend/src/ragstudio/services/query_service.py`
- `backend/src/ragstudio/services/retrieval_orchestrator.py`
- `backend/src/ragstudio/services/retrieval_evidence.py`
- `backend/src/ragstudio/services/chunk_service.py`
- `backend/src/ragstudio/services/hybrid_chunk_search.py`
- `backend/src/ragstudio/services/reranker_service.py`
- `backend/src/ragstudio/services/llm_reranker_service.py`
- `backend/src/ragstudio/services/runtime_answer_service.py`

The current design has useful building blocks, but the planner is shallow and metadata retrieval is a single ranked list. If the correct chunk is not in that early list, the reranker and answer service cannot recover.

## Recommended Architecture

Use Option B with C-style gates:

```text
User Query
  -> Query Understanding
  -> Retrieval Plan
  -> Multi-pass Retrieval
  -> Candidate Normalization
  -> Candidate Fusion
  -> Evidence Reranking
  -> Answer Composition
  -> Grounding Validation
  -> Final Answer + Trace
```

This keeps the implementation focused on answering quality while using evaluation gates from the experiment platform to prevent regressions.

## Component Design

### 1. Query Understanding

Create a small query-understanding layer that converts raw text into a structured `QueryUnderstanding`.

Responsibilities:

- Classify intent.
- Extract answer-bearing phrases.
- Extract exact references.
- Extract reference aliases and canonical/reference hints.
- Identify whether the user asks for a verse, count, title, summary, comparison, or image/table explanation.
- Produce retrieval rewrites.

Example:

```json
{
  "intent": "phrase_lookup",
  "answer_type": "reference",
  "target_phrases": ["allah is the light of the heavens and the earth"],
  "required_terms": ["allah", "light", "heavens", "earth"],
  "rewritten_queries": [
    "allah is the light of the heavens and the earth",
    "\"Allah is the Light of the heavens and the earth\""
  ],
  "reference_hints": [],
  "must_cite": true
}
```

Example:

```json
{
  "intent": "request_lookup",
  "answer_type": "reference",
  "target_phrases": ["guide us to the straight path"],
  "required_terms": ["guide", "straight", "path"],
  "rewritten_queries": [
    "guide us to the straight path",
    "straight path guidance request"
  ],
  "reference_hints": [],
  "must_cite": true
}
```

The first version should be deterministic and local. An optional AI query-understanding provider can be added behind a feature flag later, but deterministic extraction must be the baseline so tests remain stable.

### 2. Retrieval Plan

Create a `RetrievalPlan` that is richer than the current `plan_for_query()` result.

Responsibilities:

- Decide which retrieval passes to run.
- Set per-pass limits.
- Record expected evidence type.
- Carry query rewrites and target phrases.
- Carry validation expectations.

Example passes:

- `reference_exact`
- `phrase_exact`
- `normalized_phrase`
- `keyword`
- `metadata_semantic`
- `native`
- `graph_neighbors`

The plan should include a trace-friendly description of why each pass was selected.

### 3. Multi-pass Retrieval

Add a retrieval pipeline that runs multiple bounded passes and merges candidate lists before reranking.

For Quran-style failures, the critical passes are:

- `phrase_exact`: find chunks containing extracted answer-bearing phrase.
- `normalized_phrase`: find chunks containing normalized paraphrases.
- `keyword`: current hybrid scoring over original query.
- `reference_exact`: direct reference lookup when a reference is present.
- `neighbors`: include previous/next verse only after a strong seed is found.

The correct chunk should enter the candidate pool even when the original query contains extra instructions such as "find the verse that says" or "summarize the image used."

### 4. Candidate Normalization

Normalize candidates into a richer evidence model before fusion.

Fields should include:

- `candidate_id`
- `chunk_id`
- `document_id`
- `text`
- `source_location`
- `reference`
- `canonical_reference`
- `retrieval_pass`
- `base_score`
- `match_features`
- `supporting_phrases`
- `risks`

The current `EvidenceCandidate` can be extended or wrapped. The design should avoid spreading ad hoc score fields across chunk metadata.

### 5. Candidate Fusion

Fusion should combine candidates from all passes while preserving why they were retrieved.

Rules:

- Deduplicate by chunk id, runtime source id, then text fingerprint.
- Keep all retrieval tools/passes in metadata.
- Prefer candidates with stronger direct-answer signals over broad topical matches.
- Avoid letting generic term coverage outrank exact phrase or request-form matches.

Fusion should be deterministic and explainable.

### 6. Evidence Reranking

Keep `RerankerService` as a separate service.

The orchestrator should improve reranker inputs:

- Rerank a broader candidate pool, not only the final top 8 from metadata search.
- Include query understanding in the reranker prompt.
- Include reference/phrase match features so the reranker can prefer direct evidence.
- Respect a latency budget and fall back to deterministic ranking if reranking fails.

The first version can keep reranking optional and disabled by default if the active profile has no reranker. The architecture should still prepare candidates so enabling LLM rerank later is valuable.

### 7. Answer Composition

Keep `RuntimeAnswerService` as the answer composer, but improve its prompt input.

The evidence prompt should include:

- Source label.
- Reference label.
- Retrieval reasons.
- Extracted target phrase when matched.
- Clear instruction that answer must cite the source supporting each key claim.

If validation later fails, the orchestrator can return a grounded fallback message or a corrected answer.

### 8. Grounding Validation

Add a post-answer validation stage.

The first version should be deterministic:

- Verify every cited source label exists.
- Verify expected reference is cited for exact-reference or phrase-lookup plans when present in evidence.
- Detect unsupported "not in evidence" answers when a high-confidence exact/phrase candidate is present.
- Flag when answer names a reference that is not in sources.

Optional AI validation can be added later for nuanced claim support, but deterministic checks should be the default gate.

Validation result should appear in run traces and timings, not silently disappear.

### 9. Evaluation Gates

Add regression tests and evaluation cases for known failures:

- "Find the verse that says Allah is the Light of the heavens and the earth. Summarize the image used"
  - Expected source: document reference `24:35`.
  - Expected answer cites `24:35`.
  - Must not say the verse is missing from evidence.

- "Which verse asks for guidance to the straight path?"
  - Expected source for this PDF: `1:5`.
  - Note: this PDF labels "Guide us to the straight path" as `[1:5]`; common canonical numbering may call it `[1:6]`.
  - Expected answer cites the document reference, with optional canonical alias later.

Evaluation should check source correctness, not only answer text.

## Data Flow

```text
QueryService.run_query()
  -> RetrievalOrchestrator.query()
     -> QueryUnderstandingService.understand(query)
     -> RetrievalPlanner.plan(understanding, query_config)
     -> RetrievalPipeline.retrieve(plan)
        -> ChunkService.search() for keyword/original query
        -> exact phrase/reference lookups
        -> optional native runtime retrieval
        -> optional graph expansion
     -> CandidateFusion.fuse(candidates)
     -> RerankerService.rerank(query, candidate_chunks, profile)
     -> RuntimeAnswerService.answer(query, final_evidence, profile)
     -> GroundingValidator.validate(answer, final_evidence, plan)
     -> OrchestratedAnswer(answer, sources, traces, validation, timings)
```

## Error Handling

The orchestrator should degrade by stage:

- Query understanding failure: fall back to original query and semantic/keyword plan.
- Native retrieval timeout: continue with metadata passes and mark native as degraded.
- Reranker failure: continue with deterministic fused ranking and preserve trace.
- Graph failure: continue without graph candidates and preserve trace.
- Answer generation failure: return failed run with error type and timings.
- Validation failure: return answer with validation trace if minor; return grounded fallback if the answer contradicts high-confidence evidence.

## Trace Requirements

Traces should make failures explainable:

- Query understanding output.
- Retrieval plan.
- Per-pass candidate counts.
- Top candidates with pass names and scores.
- Fusion/deduplication decisions.
- Reranker result or skip reason.
- Grounding validation result.
- Timings per stage.

This is essential for UI debugging and for future optimizer decisions.

## Testing Strategy

Unit tests:

- Query understanding extraction for phrase lookup, request lookup, exact reference, count, and summary.
- Retrieval planner pass selection.
- Candidate fusion direct-match precedence.
- Grounding validator catches "not in evidence" when exact candidate exists.

Service tests:

- Metadata retrieval includes `24:35` for the Light query.
- Metadata retrieval includes document reference `1:5` for the straight-path query.
- Orchestrator returns evidence in the right order with reranker disabled.
- Orchestrator degrades when native retrieval times out.

Integration/UI smoke:

- Query page returns `24:35` for the Light query.
- Query page returns `1:5` for the straight-path query.
- Existing experiment and optimizer flows still run.

## Migration Strategy

Implement incrementally:

1. Add new types and deterministic query understanding.
2. Add multi-pass metadata retrieval while keeping current `ChunkService.search()`.
3. Replace one-off `HybridChunkSearch` boosts with reusable query-understanding-driven scoring.
4. Extend fusion traces.
5. Add grounding validation.
6. Add eval cases and tests.

Keep the existing API response shape compatible. Add new trace fields instead of removing old ones.

## Success Criteria

- The two known Quran failures pass without one-off query-specific boosts.
- Correct evidence appears in the top source for phrase and request lookup queries.
- Reranker receives a broader candidate pool with direct-match candidates included.
- Answers that cite model knowledge without evidence are detected.
- Existing query, experiment, comparison, optimizer, and dashboard flows still work.
- Tests cover the new pipeline units and the two regression cases.

