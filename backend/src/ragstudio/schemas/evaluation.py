from typing import Any

from ragstudio.schemas.common import StudioModel


class EvaluationCaseIn(StudioModel):
    id: str
    query: str
    documents: list[str] = []
    expected_answer: str | None = None
    expected_sources: list[str] = []
    must_include: list[str] = []
    must_avoid: list[str] = []
    expected_media: list[dict[str, Any]] = []
    expected_structure: dict[str, Any] = {}
    rubric: dict[str, str] = {}
    objective: dict[str, Any] = {}
    variant_hints: dict[str, list[str]] = {}


class EvaluationSetOut(StudioModel):
    id: str
    name: str
    cases: list[EvaluationCaseIn]


class EvaluationSetPage(StudioModel):
    items: list[EvaluationSetOut]
    total: int
