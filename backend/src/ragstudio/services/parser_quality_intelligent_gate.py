from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import DomainMetadata

INFO_LEVELS = {"info"}
EQUATION_BLOCK_TYPES = {"equation", "equation_interline", "interline_equation"}


class ParserQualityIntelligentGate:
    def classify_warnings(
        self,
        warnings: list[dict[str, Any]],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> list[dict[str, Any]]:
        return [
            self.classify_warning(warning, domain_metadata=domain_metadata)
            for warning in warnings
            if isinstance(warning, dict)
        ]

    def classify_warning(
        self,
        warning: dict[str, Any],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> dict[str, Any]:
        code = warning.get("code")
        block_type = str(warning.get("block_type") or "").strip().casefold()
        layout_policy = self._layout_policy(domain_metadata)

        if code == "recovered_text_from_misclassified_block" and block_type in (
            EQUATION_BLOCK_TYPES
        ):
            policy = self._policy_item(
                layout_policy,
                "misclassified_block_policy",
                "equation_with_recovered_text",
            )
            if policy:
                return self._classified(
                    warning,
                    policy=policy,
                    reason="layout_quality_policy.equation_with_recovered_text",
                )

        if code == "recovered_text_from_disallowed_block":
            policy = self._policy_item(
                layout_policy,
                "disallowed_block_policy",
                "text_bearing_disallowed_block",
            )
            if policy:
                return self._classified(
                    warning,
                    policy=policy,
                    reason="layout_quality_policy.text_bearing_disallowed_block",
                )

        return {
            **warning,
            "severity": str(warning.get("severity") or "warn"),
            "quality_gate_action": str(warning.get("quality_gate_action") or "review_warning"),
            "suppressed_from_counts": bool(warning.get("suppressed_from_counts", False)),
        }

    def _classified(
        self,
        warning: dict[str, Any],
        *,
        policy: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        warning_level = str(policy.get("warning_level") or "warn")
        action = str(policy.get("action") or "recover_as_text")
        if action == "block":
            warning_level = "block"
        return {
            **warning,
            "severity": warning_level,
            "quality_gate_action": "accepted_recovery" if action == "recover_as_text" else action,
            "suppressed_from_counts": action != "block" and warning_level in INFO_LEVELS,
            "quality_gate_reason": reason,
        }

    def _layout_policy(self, domain_metadata: DomainMetadata | None) -> dict[str, Any]:
        custom_json = (
            domain_metadata.custom_json
            if domain_metadata is not None and isinstance(domain_metadata.custom_json, dict)
            else {}
        )
        layout_policy = custom_json.get("layout_quality_policy")
        return layout_policy if isinstance(layout_policy, dict) else {}

    def _policy_item(
        self,
        layout_policy: dict[str, Any],
        section_name: str,
        item_name: str,
    ) -> dict[str, Any]:
        section = layout_policy.get(section_name)
        if not isinstance(section, dict):
            return {}
        item = section.get(item_name)
        return item if isinstance(item, dict) else {}
