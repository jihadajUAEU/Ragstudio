from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.block_types import EQUATION_BLOCK_TYPES

INFO_LEVELS = {"info"}
RECOVER_AS_TEXT_ACTION = "recover_as_text"


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
        code = self._normalized_key(warning.get("code"))
        block_type = self._normalized_key(warning.get("block_type"))
        layout_policy = self._layout_policy(domain_metadata)

        policy, reason = self._warning_policy(layout_policy, code, block_type)
        if not policy:
            policy, reason = self._block_type_policy(layout_policy, block_type)
        if not policy:
            policy, reason = self._legacy_policy(layout_policy, code, block_type)
        if policy:
            return self._classified(warning, policy=policy, reason=reason)

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
        action = str(policy.get("action") or RECOVER_AS_TEXT_ACTION)
        if action == "block":
            warning_level = "block"
        return {
            **warning,
            "severity": warning_level,
            "quality_gate_action": (
                "accepted_recovery" if action == RECOVER_AS_TEXT_ACTION else action
            ),
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

    def _warning_policy(
        self,
        layout_policy: dict[str, Any],
        code: str,
        block_type: str,
    ) -> tuple[dict[str, Any], str]:
        warning_policy = layout_policy.get("warning_policy")
        if not isinstance(warning_policy, dict):
            return {}, ""
        code_key, code_policy = self._normalized_mapping_item(warning_policy, code)
        if not code_key or not isinstance(code_policy, dict):
            return {}, ""

        by_block_type = code_policy.get("by_block_type")
        if isinstance(by_block_type, dict):
            block_type_key, policy = self._normalized_mapping_item(by_block_type, block_type)
            if block_type_key and isinstance(policy, dict):
                return (
                    policy,
                    "layout_quality_policy.warning_policy."
                    f"{code_key}.by_block_type.{block_type_key}",
                )

        default_policy = code_policy.get("default")
        if isinstance(default_policy, dict):
            return default_policy, f"layout_quality_policy.warning_policy.{code_key}.default"
        return {}, ""

    def _block_type_policy(
        self,
        layout_policy: dict[str, Any],
        block_type: str,
    ) -> tuple[dict[str, Any], str]:
        block_type_policy = layout_policy.get("block_type_policy")
        if not isinstance(block_type_policy, dict):
            return {}, ""
        block_type_key, policy = self._normalized_mapping_item(block_type_policy, block_type)
        if block_type_key and isinstance(policy, dict):
            return policy, f"layout_quality_policy.block_type_policy.{block_type_key}"
        return {}, ""

    def _legacy_policy(
        self,
        layout_policy: dict[str, Any],
        code: str,
        block_type: str,
    ) -> tuple[dict[str, Any], str]:
        if code == "recovered_text_from_misclassified_block" and block_type in (
            EQUATION_BLOCK_TYPES
        ):
            policy = self._policy_item(
                layout_policy,
                "misclassified_block_policy",
                "equation_with_recovered_text",
            )
            if policy:
                return policy, "layout_quality_policy.equation_with_recovered_text"

        if code == "recovered_text_from_disallowed_block":
            policy = self._policy_item(
                layout_policy,
                "disallowed_block_policy",
                "text_bearing_disallowed_block",
            )
            if policy:
                return policy, "layout_quality_policy.text_bearing_disallowed_block"

        return {}, ""

    def _normalized_mapping_item(
        self,
        value: dict[str, Any],
        key: str,
    ) -> tuple[str, Any]:
        for item_key, item_value in value.items():
            if self._normalized_key(item_key) == key:
                return str(item_key), item_value
        return "", None

    def _normalized_key(self, value: Any) -> str:
        return str(value or "").strip().casefold()
