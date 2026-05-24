from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    prompt_id: str
    version: str
    system: str = ""
    user_prefix: str = ""

    def metadata(self) -> dict[str, str]:
        return {"prompt_id": self.prompt_id, "prompt_version": self.version}


ANSWER_PROMPT = PromptTemplate(
    prompt_id="runtime_answer.v1",
    version="2026-05-24",
    system=(
        "Answer only from the provided evidence. Cite evidence by its "
        "label, such as [S1] or [S2]. If the evidence does not support "
        "an answer, say that clearly and do not guess."
    ),
)

LLM_RERANKER_PROMPT = PromptTemplate(
    prompt_id="llm_reranker.v1",
    version="2026-05-24",
    system=(
        "Rank evidence for the user query. Return only a JSON array. "
        "Each item must contain index, score, and reason. Use zero-based "
        "indexes from the provided evidence."
    ),
)

AUTOSUGGEST_PROMPT = PromptTemplate(
    prompt_id="domain_metadata_autosuggest.v1",
    version="2026-05-24",
    user_prefix="You classify documents for a RAG indexing system.",
)

VISION_RECOVERY_PROMPT = PromptTemplate(
    prompt_id="vision_recovery.v1",
    version="2026-05-24",
    user_prefix="Extract visible text from a cropped document block.",
)
