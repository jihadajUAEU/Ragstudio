# Ragstudio Synthetic Sample Pack

This sample pack gives reviewers a safe, repeatable way to see how Ragstudio exposes document-quality failures before they become answer evidence.

The documents are synthetic. They are inspired by public document types, but the text is not copied from the internet, customer files, private corpora, or provider outputs.

## What It Covers

- parser warnings and quality gates,
- chunk metadata and reference labels,
- exact-reference retrieval,
- table and numeric grounding,
- graph/citation relationships,
- reranker traces,
- multilingual text,
- should-not-answer prompts.

## Quick Path

1. Read `sources/catalogue.md` to understand the public document types that inspired the pack.
2. Upload files from `documents/` into Ragstudio.
3. Attach the matching file from `metadata/`.
4. Import `evaluations/sample-pack-evaluation-set.json` where evaluation import is available.
5. Follow `RUNBOOK.md` to inspect the app and capture screenshots.

## Safety Rule

Only screenshots marked safe in `screenshots/signoff.json` should be published. Pending screenshots are local verification evidence only.
