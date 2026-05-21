# Retrieval Quality Baseline

Date: 2026-05-21

This baseline blocks default-on vector, FTS, fusion, reranker, graph expansion,
and context assembly changes until they preserve or improve deterministic
retrieval behavior. The repo-local pytest gate uses only synthetic data and does
not require a database, provider key, private model host, or network access.

## Synthetic Query Classes

- Exact reference lookup: a known book/chapter/hadith or ayah reference must
  rank first from canonical metadata or lexical-reference retrieval.
- Conversational terms: partial user phrasing must still find the same direct
  evidence and preserve the expected source.
- Arabic exact term: normalized Arabic-token lookup must rank direct Arabic
  evidence above broad semantic evidence.
- Graph expansion: graph neighbors must be relevant to high-confidence
  canonical, lexical, or metadata seeds.
- Layout evidence: table, figure, and equation evidence must keep source,
  reference, and page/layout provenance through context assembly.

## Metrics

| Metric | Definition | V1 gate |
| --- | --- | --- |
| `exact_reference_hit_rate` | Share of exact-reference query cases whose top result has the expected reference id. | `>= 1.00` |
| `source_accuracy` | Share of query cases whose top result comes from an expected source id. | `>= 1.00` |
| `graph_expansion_precision` | Relevant graph-lane candidates divided by all graph-lane candidates. | `>= 0.80` |
| `reranker_ndcg` | Mean NDCG@3 over graded synthetic result lists after reranking. | `>= 0.98` |
| `context_grounding_rate` | Required context evidence ids present in assembled context divided by all required evidence ids. | `>= 1.00` |

## Default-On Gate

A vector, FTS, fusion, reranker, graph expansion, or context assembly change can
become default only when:

- `backend/tests/test_retrieval_quality_eval.py` passes,
- direct exact-reference behavior does not regress,
- top-result source accuracy does not regress,
- graph expansion precision remains at or above the V1 threshold,
- reranker NDCG remains at or above the V1 threshold,
- assembled context remains fully grounded in required evidence,
- any accepted regression is documented with the changed query class, metric,
  reason, and follow-up owner before merge.

## Focused Validation

Run the lightweight gate with:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_quality_eval.py -q
```

The gate is intentionally synthetic. It makes ranking and grounding contracts
measurable before enabling broader live-capture or corpus-backed evaluation.
