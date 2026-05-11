# Quran Experiment Sample Pack

This sample pack is designed for `/Users/meet/Downloads/quran_arabic_english.pdf`.
It gives you ready-to-use inputs for Ragstudio's `Documents`, `Evaluation`,
`Variants`, `Experiments`, `Comparison`, and `Optimizer` pages.

## Files

- `quran-domain-metadata.json`: upload or reindex metadata for the Quran/Tafseer profile.
- `quran-evaluation-set.json`: import this on the `Evaluation` page.
- `quran-variants.json`: create these on the `Variants` page or with `seed-via-api.sh`.
- `experiment-objective.json`: paste into `Experiments` objective JSON.
- `optimizer-objective.json`: paste into `Optimizer` objective JSON.
- `comparison-checklist.md`: what to compare after runs exist.
- `seed-via-api.sh`: optional helper that creates the variants and imports the evaluation set.

## Recommended Workflow

1. Start the app with `./scripts/dev.sh`.
2. Open `Documents` and upload `/Users/meet/Downloads/quran_arabic_english.pdf`.
3. Use `quran-domain-metadata.json` as the domain metadata when uploading or reindexing.
4. Open `Variants` and create the four variants from `quran-variants.json`.
5. Open `Evaluation` and import `quran-evaluation-set.json`.
6. Open `Experiments`, select the Quran document, the imported evaluation set, and all four variants.
7. Paste `experiment-objective.json` into the objective JSON field and run the experiment.
8. Open `Comparison` and compare the best precise/balanced/broad/fast runs using `comparison-checklist.md`.
9. Open `Optimizer`, paste `optimizer-objective.json`, and recommend the strongest variant for the experiment.

## What This Tests

- Exact reference retrieval, such as `2:255`.
- Phrase retrieval, such as `Light upon light`.
- Short surah/ayah answers, such as `1:5`.
- Cross-verse context, such as `55:19-20`.
- Hallucination control by avoiding unsupported external sources.
- Variant trade-offs between precise citation, broad context, reranking, and fast retrieval.

