"""Command line interface for Ragstudio proof packet validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ragstudio.proof_packet.manifest import build_export_manifest
from ragstudio.proof_packet.validator import DEFAULT_PACKET_ROOT, validate_packet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a Ragstudio public proof packet.")
    parser.add_argument(
        "--packet",
        type=Path,
        default=DEFAULT_PACKET_ROOT,
        help="Proof packet root to validate.",
    )
    parser.add_argument("--json", action="store_true", help="Emit compact machine JSON only.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    parser.add_argument("--verbose", action="store_true", help="Show detailed findings.")
    parser.add_argument(
        "--export-manifest",
        action="store_true",
        help="Emit static export manifest metadata instead of the validation result.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_packet(args.packet, strict=args.strict)

    if args.export_manifest:
        payload = build_export_manifest(args.packet, validation_result=result)
        print(json.dumps(payload, indent=None if args.json else 2, sort_keys=True))
    elif args.json:
        print(json.dumps(result.to_dict(), separators=(",", ":"), sort_keys=True))
    else:
        print(_format_human(result, args.packet, verbose=args.verbose))

    return 0 if result.status == "passed" else 1


def _format_human(result, packet: Path, *, verbose: bool) -> str:
    lines = [
        f"Ragstudio proof packet: {packet}",
        f"Status: {result.status}",
        f"Errors: {len(result.errors)}",
        f"Warnings: {len(result.warnings)}",
    ]
    findings = [*result.errors, *result.warnings]
    if findings:
        lines.append("")
        lines.append("Findings:")
        for finding in findings:
            lines.append(f"- {finding.code} {finding.path}: {finding.message}")
            if verbose:
                lines.append(f"  Recovery: {finding.recovery}")
    else:
        lines.append("Proof packet validation passed.")
    if result.warnings and result.status == "passed":
        lines.append("Use --strict to treat warnings as failures for automation.")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
