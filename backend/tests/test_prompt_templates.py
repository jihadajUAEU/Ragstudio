from ragstudio.services.prompt_templates import (
    ANSWER_PROMPT,
    AUTOSUGGEST_PROMPT,
    LLM_RERANKER_PROMPT,
    VISION_RECOVERY_PROMPT,
)


def test_prompt_templates_are_named_and_versioned() -> None:
    prompts = [
        ANSWER_PROMPT,
        LLM_RERANKER_PROMPT,
        AUTOSUGGEST_PROMPT,
        VISION_RECOVERY_PROMPT,
    ]

    assert [prompt.prompt_id for prompt in prompts] == [
        "runtime_answer.v1",
        "llm_reranker.v1",
        "domain_metadata_autosuggest.v1",
        "vision_recovery.v1",
    ]
    assert all(prompt.version == "2026-05-24" for prompt in prompts)


def test_answer_prompt_keeps_grounding_contract() -> None:
    assert "Answer only from the provided evidence" in ANSWER_PROMPT.system
    assert "If the evidence does not support an answer" in ANSWER_PROMPT.system


def test_llm_reranker_prompt_keeps_json_contract() -> None:
    assert "Return only a JSON array" in LLM_RERANKER_PROMPT.system
    assert "zero-based" in LLM_RERANKER_PROMPT.system
