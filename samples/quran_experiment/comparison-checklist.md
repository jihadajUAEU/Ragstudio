# Quran Run Comparison Checklist

Use this after the experiment has created runs.

## Compare These Pairs

1. `Quran precise reference` vs `Quran balanced grounded`
2. `Quran balanced grounded` vs `Quran broad neighbor context`
3. `Quran precise reference` vs `Quran fast lexical`
4. Best optimizer-selected variant vs the fastest successful variant

## What To Inspect

- `Answer`: Does it answer only from the uploaded Quran translation?
- `Sources`: Is the required surah:ayah present?
- `Chunk traces`: Did the intended chunk make it into generation context?
- `Timings`: Did extra top_k or reranking materially increase latency?
- `Failure mode`: Is the weaker run missing a reference, adding external context, or producing too much neighboring text?

## Expected Pattern

- `precise` should win exact reference questions.
- `balanced` should be a good default when both phrase and reference questions matter.
- `broad` should help adjacent-verse questions, especially `55:19-20`.
- `fast` should be useful for quick checks but may lose harder semantic or neighbor cases.

