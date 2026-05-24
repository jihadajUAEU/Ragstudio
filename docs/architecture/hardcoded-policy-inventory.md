# Hardcoded Policy Inventory

Ragstudio keeps product runtime defaults, retrieval policy, prompts, and public-safety
redaction rules in named modules so behavior can be inspected and tested before tuning.

## Standard Defaults

- Runtime defaults live in `backend/src/ragstudio/services/runtime_defaults.py`.
- Retrieval scoring defaults live in `backend/src/ragstudio/services/retrieval_policy.py`.
- Prompt identifiers and versions live in `backend/src/ragstudio/services/prompt_templates.py`.
- Public-safety redaction rules live in `backend/src/ragstudio/services/redaction_registry.py`.
- Operational limits and eval weights live in `backend/src/ragstudio/services/operational_policy.py`.
- Built-in script/reference/query regexes live in `backend/src/ragstudio/services/reference_regex_registry.py`.
- Remaining protocol constants and product policies are classified in `backend/src/ragstudio/services/static_policy_catalog.py`.

## Design Rules

- Changing a retrieval score requires a focused test that asserts ordering and trace metadata.
- Changing prompt wording requires a prompt version update and a test for the required output contract.
- Changing redaction rules requires proof-packet and document-evidence safety tests.
- Frontend runtime defaults should come from `/api/defaults`; local values are offline fallbacks only.

## Remaining Tunable Areas

- Domain-specific lexical adapters should own corpus-specific synonyms and reference behavior.
- Layout proximity and chunking thresholds should become domain-profile options when eval coverage exists.
- Evaluation scoring should keep the current substring scorer as a baseline and add rubric-specific adapters separately.
- User-provided custom regexes should remain validated by document/reference contract compilers, not promoted to global built-ins.
- Proof packet IDs, proof error codes, provider manifest vocabulary, query-hypothesis vocabularies, and block-type vocabularies are protocol constants. Do not tune them like scoring weights.
