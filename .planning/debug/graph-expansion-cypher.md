---
status: resolved
trigger: "After graph projection repair, Tafseer query traces reported `CypherSyntaxError` from graph expansion."
created: 2026-05-16T04:00:32Z
updated: 2026-05-16T04:00:32Z
---

## Current Focus

hypothesis: Confirmed. Graph expansion wrapped two UNION branches in a subquery but ended the outer query with `LIMIT $limit` without first returning the subquery columns.
test: `test_graph_expansion_scopes_query_to_workspace_label` now asserts the generated Cypher has an outer `RETURN` before the final limit.
expecting: The graph expansion query should parse in Neo4j and return hydrated graph candidates from projected Tafseer relationships.
next_action: Final report after verification.

## Symptoms

expected: `/api/query` graph expansion should use the succeeded graph projection as an expansion lane.
actual: Query traces degraded graph expansion with `CypherSyntaxError`.
errors: `Query cannot conclude with WITH ... LIMIT $limit`
reproduction: Run graph expansion after the Tafseer graph projection succeeds.
started: Observed while checking whether Tafseer search was using the graph.

## Evidence

- timestamp: 2026-05-16T04:00:32Z
  checked: Generated Cypher in `GraphExpansionService._run_query`.
  found: The query returned columns inside `CALL { ... }`, then concluded with `LIMIT $limit` at the outer level.
  implication: Neo4j requires an outer `RETURN` after the subquery, so graph expansion was syntactically invalid even though graph projection data existed.
- timestamp: 2026-05-16T04:00:32Z
  checked: Unit, orchestrator, runtime query, Ruff, and live graph expansion smoke checks.
  found: Unit tests pass, nearby retrieval/query tests pass, Ruff passes, and live Tafseer graph expansion returns candidates instead of raising `CypherSyntaxError`.
  implication: The Cypher syntax failure is fixed and graph expansion is usable again.

## Resolution

root_cause: The graph expansion Cypher subquery had no top-level `RETURN` before the final `LIMIT`.
fix: Return the subquery columns at the outer level before applying `LIMIT $limit`.
verification: `backend/tests/test_graph_expansion_service.py`, `backend/tests/test_retrieval_orchestrator.py`, `backend/tests/test_runtime_query_service.py`, Ruff, and a live Neo4j graph expansion smoke check.
files_changed: ["backend/src/ragstudio/services/graph_expansion_service.py", "backend/tests/test_graph_expansion_service.py", ".planning/debug/graph-expansion-cypher.md"]
