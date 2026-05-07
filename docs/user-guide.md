# RAG-Anything Studio User Guide

RAG-Anything Studio is a local workbench for configuring retrieval pipelines, uploading source material, comparing variants, and evaluating answer quality.

## Core Flow

1. Configure provider, model, embedding, and storage defaults in Settings.
2. Upload source files in Documents.
3. Index or inspect chunks from the Chunk Inspector after ingestion.
4. Create variants for different retrieval and generation strategies.
5. Ask questions in Query and review the answer, retrieved chunks, and evidence.
6. Import evaluation files in Evaluation.
7. Run Experiments to compare variants against an evaluation set.
8. Review outputs and scores in Comparison.
9. Use Optimizer to recommend stronger variant settings from recorded runs.
10. Check Graph and Diagnostics when pipeline state or feature support is unclear.

## Evaluation File Formats

Studio accepts JSONL, JSON, YAML, and CSV evaluation imports. JSONL is the canonical repeatable format.

Every evaluation case needs an `id`, a `query`, and at least one expected-output signal such as `expected_answer`, `expected_sources`, `must_include`, `expected_structure`, `rubric`, or `expected_media`.

### JSONL

Use one evaluation case object per line:

```jsonl
{"id":"case-1","query":"What changed in the contract?","expected_answer":"The renewal term changed.","must_include":["renewal term"]}
{"id":"case-2","query":"Which source mentions pricing?","expected_sources":["pricing.pdf"]}
```

### JSON

Use either an array of cases or an object with a `cases` array:

```json
{
  "cases": [
    {
      "id": "case-1",
      "query": "What changed in the contract?",
      "expected_answer": "The renewal term changed."
    }
  ]
}
```

### YAML

YAML follows the same shape as JSON:

```yaml
cases:
  - id: case-1
    query: What changed in the contract?
    expected_answer: The renewal term changed.
    must_include:
      - renewal term
```

### CSV

CSV imports map columns into evaluation case fields. Use simple scalar columns for `id`, `query`, and `expected_answer`; list-like fields such as `must_include`, `must_avoid`, `expected_sources`, and `documents` can be comma-separated values.

```csv
id,query,expected_answer,must_include,expected_sources
case-1,What changed in the contract?,The renewal term changed.,renewal term,contract.pdf
```
