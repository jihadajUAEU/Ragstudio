---
status: in-progress
quick_id: 260516-mnt
slug: fix-task-4-review-warning-preserve-lexic
---

Fix Task 4 review warning by preserving lexical expansion match type through query
understanding passes and metadata retrieval.

Steps:
- Add an optional match_type field to RetrievalPass.
- Populate match_type from LexicalExpansion when building lexical_expanded_token passes.
- Use the pass-level match_type in metadata retrieval match features with conservative fallback.
- Add focused regression tests and run requested pytest and ruff commands.
- Commit the resulting scoped changes.
