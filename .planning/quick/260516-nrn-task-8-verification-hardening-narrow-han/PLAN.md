# Task 8 Verification Hardening

## Goal

Narrow the Quranic `hanan` transliteration expansion and avoid running lower-priority metadata fallback passes after direct evidence already returns candidates.

## Steps

1. Update the Arabic transliteration lexicon to remove broad `حنان` from `hanan`.
2. Short-circuit metadata retrieval after successful direct evidence metadata passes while preserving trace for executed passes.
3. Update focused backend tests for expansion behavior, fallback skipping, and existing Arabic exact behavior.
4. Run the requested pytest and ruff commands.
5. Commit as `fix: speed lexical direct evidence retrieval`.
