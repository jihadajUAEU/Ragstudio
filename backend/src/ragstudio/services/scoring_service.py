import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Run, Score
from ragstudio.schemas.evaluation import EvaluationCaseIn


class ScoringService:
    def __init__(self, session: AsyncSession | None = None):
        self.session = session

    def score(self, run: Run, case: EvaluationCaseIn) -> Score:
        details = self.score_answer(run.answer, case)
        return Score(run_id=run.id, total=details["total"], details=details)

    async def create_score(self, run: Run, case: EvaluationCaseIn) -> Score:
        if self.session is None:
            raise RuntimeError("ScoringService requires a session to persist scores")
        score = self.score(run, case)
        self.session.add(score)
        return score

    def score_answer(self, answer: str, case: EvaluationCaseIn) -> dict[str, Any]:
        answer_text = answer.lower()
        expected_terms = self._terms(case.expected_answer or "")
        include_terms = [item.strip().lower() for item in case.must_include if item.strip()]
        avoid_terms = [item.strip().lower() for item in case.must_avoid if item.strip()]

        expected_hits = [term for term in expected_terms if term in answer_text]
        include_hits = [term for term in include_terms if term in answer_text]
        include_misses = [term for term in include_terms if term not in answer_text]
        avoid_hits = [term for term in avoid_terms if term in answer_text]

        total = 0.0
        weights = 0.0
        if expected_terms:
            total += (len(expected_hits) / len(expected_terms)) * 50.0
            weights += 50.0
        if include_terms:
            total += (len(include_hits) / len(include_terms)) * 35.0
            weights += 35.0
        if avoid_terms:
            total += ((len(avoid_terms) - len(avoid_hits)) / len(avoid_terms)) * 15.0
            weights += 15.0

        normalized_total = round((total / weights) * 100) if weights else 100
        return {
            "total": int(max(0, min(100, normalized_total))),
            "expected_terms": sorted(expected_terms),
            "expected_hits": sorted(expected_hits),
            "must_include_hits": include_hits,
            "must_include_missing": include_misses,
            "must_avoid_hits": avoid_hits,
        }

    def _terms(self, value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", value.lower()))
