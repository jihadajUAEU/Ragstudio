---
quick_id: 260515-w2m
status: complete
completed: 2026-05-15T19:12:35Z
---

# Repository-Wide Codex Security Scan Summary

Ran a repository-wide Codex Security scan for Ragstudio at commit
`178108582db6d9c67cf07113cba2c5e0dcb78ba2`.

Final report:

`/tmp/codex-security-scans/Ragstudio/178108582db6_20260515T190551Z/report.md`

Reportable findings:

1. Compose publishes Postgres and Neo4j on all interfaces with static credentials.
2. Saved LLM key can be relayed to a caller-controlled test URL.
3. Saved embedding key can be relayed to a caller-controlled test URL.
4. Reranker LLM mode bypasses the reranker allowlist and can relay the saved LLM key.
5. Proof packet redaction misses private hostname-only endpoints despite the public
   artifact policy claiming that class is blocked.

No code fixes were made.
