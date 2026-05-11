from __future__ import annotations

from typing import Any

import httpx
from ragstudio.services.retrieval_evidence import EvidenceCandidate


class RuntimeAnswerService:
    async def answer(
        self,
        query: str,
        evidence: list[EvidenceCandidate],
        profile: Any,
    ) -> tuple[str, dict[str, Any]]:
        if not evidence:
            return "The available evidence does not support an answer to this question.", {}

        payload = {
            "model": profile.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer only from the provided evidence. Cite evidence by its "
                        "label, such as [S1] or [S2]. If the evidence does not support "
                        "an answer, say that clearly and do not guess."
                    ),
                },
                {"role": "user", "content": self._prompt(query, evidence)},
            ],
            "temperature": 0.2,
        }
        timeout = (getattr(profile, "llm_timeout_ms", None) or 10_000) / 1000

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self._chat_url(str(profile.llm_base_url)),
                headers=self._headers(getattr(profile, "llm_api_key", None)),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        return self._content(body), self._usage(body)

    def _prompt(self, query: str, evidence: list[EvidenceCandidate]) -> str:
        sections = [
            f"Question: {query.strip()}",
            "",
            "Evidence:",
        ]
        for index, candidate in enumerate(evidence, start=1):
            label = f"S{index}"
            reasons = ", ".join(candidate.reasons)
            warning_codes = candidate.metadata.get("parser_quality_warning_codes")
            warnings = (
                ", ".join(warning_codes)
                if isinstance(warning_codes, list)
                and all(isinstance(code, str) for code in warning_codes)
                else ""
            )
            header = (
                f"[{label}] tool={candidate.tool} rank={candidate.tool_rank} "
                f"document={candidate.document_id or 'unknown'} "
                f"chunk={candidate.chunk_id or 'unknown'}"
                f"{f' reasons={reasons}' if reasons else ''}"
                f"{f' parser_quality_warnings={warnings}' if warnings else ''}"
            )
            sections.append(
                f"{header}\n{candidate.text.strip()}"
            )
        return "\n\n".join(sections)

    def _chat_url(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    def _headers(self, api_key: str | None) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        return headers

    def _content(self, body: Any) -> str:
        if not isinstance(body, dict):
            return ""
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        text = first.get("text")
        return text if isinstance(text, str) else ""

    def _usage(self, body: Any) -> dict[str, Any]:
        if isinstance(body, dict) and isinstance(body.get("usage"), dict):
            return body["usage"]
        return {}
