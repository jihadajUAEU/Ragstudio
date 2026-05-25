from __future__ import annotations

from ragstudio.schemas.parsing import DomainMetadata


def quality_language_from_metadata(metadata: DomainMetadata) -> str:
    if metadata.script and metadata.script.casefold() in {"arabic", "ar"}:
        return "arabic"
    if metadata.language and metadata.language.casefold() in {"arabic", "ar"}:
        return "arabic"
    custom_json = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
    quality_policy = custom_json.get("quality_policy")
    if isinstance(quality_policy, dict):
        scripts = quality_policy.get("required_scripts")
        if isinstance(scripts, list) and "arabic" in {
            str(item).casefold() for item in scripts
        }:
            return "arabic"
    return "unknown"
