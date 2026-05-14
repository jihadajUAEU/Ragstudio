# Synthetic Corpus

## Shape

The Phase 1 corpus is a deterministic synthetic Arabic + English reference-heavy
fixture. It exists to prove packet shape and evidence linkage, not corpus quality
or benchmark scale.

Files:

- `fixtures/corpus.synthetic.json`
- `fixtures/parser-warnings.synthetic.json`
- `fixtures/retrieval-traces.synthetic.json`
- `fixtures/graph-reranker.synthetic.json`

## Coverage

The corpus covers:

- Arabic reference-unit text,
- English reference-unit text,
- source locations,
- display references,
- parser-quality warnings,
- `quality_action_policy`,
- `chunk_traces`,
- `graph_projection_state`,
- `reranker_traces`.

## Representative Warning

The fixture intentionally includes `reference_unit_missing_expected_script`.
That warning demonstrates the public proof story: Ragstudio can expose
pre-retrieval document-quality failures before they silently become answer
evidence.

## Public Safety

The corpus is synthetic. It does not include Quran, Hadith, customer, provider,
or private infrastructure content. Host or IP examples, when needed, must use
reserved documentation values only.
