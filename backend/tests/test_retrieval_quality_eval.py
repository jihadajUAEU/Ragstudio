from dataclasses import dataclass
from math import log2

import pytest


@dataclass(frozen=True)
class RankedResult:
    chunk_id: str
    source_id: str
    reference_id: str | None
    lane: str
    reranker_grade: int


@dataclass(frozen=True)
class QueryCase:
    query_id: str
    query_class: str
    expected_reference_ids: tuple[str, ...]
    expected_source_ids: tuple[str, ...]
    results: tuple[RankedResult, ...]
    relevant_graph_chunk_ids: tuple[str, ...] = ()
    required_context_chunk_ids: tuple[str, ...] = ()
    assembled_context_chunk_ids: tuple[str, ...] = ()


QUALITY_THRESHOLDS = {
    "exact_reference_hit_rate": 1.0,
    "source_accuracy": 1.0,
    "graph_expansion_precision": 0.80,
    "reranker_ndcg": 0.98,
    "context_grounding_rate": 1.0,
}


SYNTHETIC_QUERY_SET = (
    QueryCase(
        query_id="exact-b13-h25",
        query_class="exact_reference",
        expected_reference_ids=("book-13-hadith-25",),
        expected_source_ids=("synthetic-hadith-book-13",),
        required_context_chunk_ids=("book-13-hadith-25",),
        assembled_context_chunk_ids=("book-13-hadith-25", "book-13-hadith-26"),
        results=(
            RankedResult(
                "book-13-hadith-25",
                "synthetic-hadith-book-13",
                "book-13-hadith-25",
                "metadata",
                3,
            ),
            RankedResult(
                "book-13-hadith-26",
                "synthetic-hadith-book-13",
                "book-13-hadith-26",
                "metadata",
                1,
            ),
            RankedResult(
                "semantic-sacrifice",
                "synthetic-topic-notes",
                None,
                "vector",
                0,
            ),
        ),
    ),
    QueryCase(
        query_id="conversational-sacrifice",
        query_class="conversational_terms",
        expected_reference_ids=("book-13-hadith-25", "book-13-hadith-26"),
        expected_source_ids=("synthetic-hadith-book-13",),
        required_context_chunk_ids=("book-13-hadith-25", "book-13-hadith-26"),
        assembled_context_chunk_ids=("book-13-hadith-25", "book-13-hadith-26"),
        results=(
            RankedResult(
                "book-13-hadith-25",
                "synthetic-hadith-book-13",
                "book-13-hadith-25",
                "metadata",
                3,
            ),
            RankedResult(
                "book-13-hadith-26",
                "synthetic-hadith-book-13",
                "book-13-hadith-26",
                "metadata",
                2,
            ),
            RankedResult(
                "sacrifice-glossary",
                "synthetic-glossary",
                None,
                "vector",
                0,
            ),
        ),
    ),
    QueryCase(
        query_id="arabic-token-wahananan",
        query_class="arabic_exact_term",
        expected_reference_ids=("quran-19-13",),
        expected_source_ids=("synthetic-quran-maryam",),
        required_context_chunk_ids=("quran-19-13",),
        assembled_context_chunk_ids=("quran-19-13",),
        results=(
            RankedResult(
                "quran-19-13",
                "synthetic-quran-maryam",
                "quran-19-13",
                "lexical_reference",
                3,
            ),
            RankedResult(
                "quran-19-14",
                "synthetic-quran-maryam",
                "quran-19-14",
                "graph",
                1,
            ),
            RankedResult(
                "mercy-topic-summary",
                "synthetic-topic-notes",
                None,
                "vector",
                0,
            ),
        ),
    ),
    QueryCase(
        query_id="graph-mercy-zakat",
        query_class="graph_expansion",
        expected_reference_ids=("quran-19-13",),
        expected_source_ids=("synthetic-quran-maryam",),
        relevant_graph_chunk_ids=(
            "quran-19-12",
            "quran-19-14",
            "maryam-crossref-zakat",
            "maryam-crossref-mercy",
        ),
        required_context_chunk_ids=("quran-19-13", "maryam-crossref-zakat"),
        assembled_context_chunk_ids=("quran-19-13", "maryam-crossref-zakat"),
        results=(
            RankedResult(
                "quran-19-13",
                "synthetic-quran-maryam",
                "quran-19-13",
                "metadata",
                3,
            ),
            RankedResult(
                "quran-19-12",
                "synthetic-quran-maryam",
                "quran-19-12",
                "graph",
                2,
            ),
            RankedResult(
                "quran-19-14",
                "synthetic-quran-maryam",
                "quran-19-14",
                "graph",
                2,
            ),
            RankedResult(
                "maryam-crossref-zakat",
                "synthetic-crossrefs",
                None,
                "graph",
                1,
            ),
            RankedResult(
                "maryam-crossref-mercy",
                "synthetic-crossrefs",
                None,
                "graph",
                1,
            ),
            RankedResult(
                "unrelated-charity-note",
                "synthetic-topic-notes",
                None,
                "graph",
                0,
            ),
        ),
    ),
    QueryCase(
        query_id="layout-table-total",
        query_class="layout_evidence",
        expected_reference_ids=("table-appeals-total-2024",),
        expected_source_ids=("synthetic-layout-report",),
        required_context_chunk_ids=("table-appeals-total-2024",),
        assembled_context_chunk_ids=("table-appeals-total-2024",),
        results=(
            RankedResult(
                "table-appeals-total-2024",
                "synthetic-layout-report",
                "table-appeals-total-2024",
                "metadata",
                3,
            ),
            RankedResult(
                "table-appeals-note-2024",
                "synthetic-layout-report",
                "table-appeals-note-2024",
                "metadata",
                2,
            ),
        ),
    ),
)


def exact_reference_hit_rate(cases: tuple[QueryCase, ...]) -> float:
    reference_cases = tuple(case for case in cases if case.query_class == "exact_reference")
    if not reference_cases:
        return 1.0

    hits = 0
    for case in reference_cases:
        top_result = _top_result(case)
        if top_result.reference_id in case.expected_reference_ids:
            hits += 1
    return hits / len(reference_cases)


def source_accuracy(cases: tuple[QueryCase, ...]) -> float:
    if not cases:
        return 1.0

    correct = sum(
        1 for case in cases if _top_result(case).source_id in case.expected_source_ids
    )
    return correct / len(cases)


def graph_expansion_precision(cases: tuple[QueryCase, ...]) -> float:
    relevant = 0
    total = 0

    for case in cases:
        if not case.relevant_graph_chunk_ids:
            continue
        relevant_graph_chunks = set(case.relevant_graph_chunk_ids)
        for result in case.results:
            if result.lane != "graph":
                continue
            total += 1
            if result.chunk_id in relevant_graph_chunks:
                relevant += 1

    if total == 0:
        return 1.0
    return relevant / total


def reranker_ndcg(cases: tuple[QueryCase, ...], *, k: int) -> float:
    scores = []
    for case in cases:
        grades = [result.reranker_grade for result in case.results[:k]]
        if not grades:
            continue

        ideal_grades = sorted(
            (result.reranker_grade for result in case.results),
            reverse=True,
        )[:k]
        ideal_dcg = _dcg(ideal_grades)
        scores.append(_dcg(grades) / ideal_dcg if ideal_dcg else 1.0)

    if not scores:
        return 1.0
    return sum(scores) / len(scores)


def context_grounding_rate(cases: tuple[QueryCase, ...]) -> float:
    grounded = 0
    required = 0

    for case in cases:
        required_chunks = set(case.required_context_chunk_ids)
        if not required_chunks:
            continue
        grounded_chunks = set(case.assembled_context_chunk_ids)
        grounded += len(required_chunks & grounded_chunks)
        required += len(required_chunks)

    if required == 0:
        return 1.0
    return grounded / required


def test_synthetic_retrieval_quality_baseline_meets_gate():
    metrics = {
        "exact_reference_hit_rate": exact_reference_hit_rate(SYNTHETIC_QUERY_SET),
        "source_accuracy": source_accuracy(SYNTHETIC_QUERY_SET),
        "graph_expansion_precision": graph_expansion_precision(SYNTHETIC_QUERY_SET),
        "reranker_ndcg": reranker_ndcg(SYNTHETIC_QUERY_SET, k=3),
        "context_grounding_rate": context_grounding_rate(SYNTHETIC_QUERY_SET),
    }

    assert metrics["exact_reference_hit_rate"] == pytest.approx(1.0)
    assert metrics["source_accuracy"] == pytest.approx(1.0)
    assert metrics["graph_expansion_precision"] == pytest.approx(0.80)
    assert metrics["reranker_ndcg"] == pytest.approx(1.0)
    assert metrics["context_grounding_rate"] == pytest.approx(1.0)

    for metric, threshold in QUALITY_THRESHOLDS.items():
        assert metrics[metric] >= threshold


def test_retrieval_quality_metrics_detect_regressions():
    regressed = (
        QueryCase(
            query_id="exact-b13-h25-regressed",
            query_class="exact_reference",
            expected_reference_ids=("book-13-hadith-25",),
            expected_source_ids=("synthetic-hadith-book-13",),
            required_context_chunk_ids=("book-13-hadith-25",),
            assembled_context_chunk_ids=("semantic-sacrifice",),
            results=(
                RankedResult(
                    "semantic-sacrifice",
                    "synthetic-topic-notes",
                    None,
                    "vector",
                    0,
                ),
                RankedResult(
                    "book-13-hadith-25",
                    "synthetic-hadith-book-13",
                    "book-13-hadith-25",
                    "metadata",
                    3,
                ),
            ),
        ),
    )

    assert exact_reference_hit_rate(regressed) == 0.0
    assert source_accuracy(regressed) == 0.0
    assert context_grounding_rate(regressed) == 0.0
    assert reranker_ndcg(regressed, k=2) < QUALITY_THRESHOLDS["reranker_ndcg"]


def _top_result(case: QueryCase) -> RankedResult:
    try:
        return case.results[0]
    except IndexError as exc:
        raise AssertionError(f"{case.query_id} has no ranked results") from exc


def _dcg(grades: list[int]) -> float:
    return sum(
        (2**grade - 1) / log2(rank + 1)
        for rank, grade in enumerate(grades, start=1)
    )
