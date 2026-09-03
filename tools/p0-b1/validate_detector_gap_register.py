from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "validation" / "p0-b1" / "DETECTOR_GAP_REGISTER.json"
OUTPUT = ROOT / "docs" / "validation" / "p0-b1" / "DETECTOR_GAP_REGISTER.md"


def main() -> int:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    rules = payload["rules"]
    expected = [f"6.{number}" for number in range(1, 27)]
    actual = [rule["rule_id"] for rule in rules]
    if actual != expected:
        raise SystemExit(f"gap register must contain ordered 6.1–6.26, got {actual}")
    allowed = set(payload["interpretation"])
    for rule in rules:
        if rule["status"] not in allowed:
            raise SystemExit(f"unknown status for {rule['rule_id']}: {rule['status']}")
        for field in (
            "implemented_evidence",
            "known_false_negative_risks",
            "known_false_positive_risks",
            "official_questions",
        ):
            if not isinstance(rule[field], list) or not rule[field]:
                raise SystemExit(f"{rule['rule_id']} missing non-empty {field}")
        if not rule["next_test_priority"]:
            raise SystemExit(f"{rule['rule_id']} missing next_test_priority")
    if payload["official_validator"] != {"target_version": "1.1.0", "observations": 0, "status": "NOT_RUN"}:
        raise SystemExit("official validator state must remain 0 / NOT_RUN")

    counts = Counter(rule["status"] for rule in rules)
    lines = [
        "# P0-B1 detector gap register",
        "",
        "> 26/26 synthetic target-condition coverage is not equivalent to 26 mature detectors. This register records current evidence and known failure modes before CDE V1.1.0 calibration.",
        "",
        "## Status distribution",
        "",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- `{status}`: {count}")
    lines += [
        "",
        "## Rule-level register",
        "",
        "| Rule | Status | Implemented evidence | Main false-negative risks | Main official question | Next test |",
        "|---|---|---|---|---|---|",
    ]
    for rule in rules:
        evidence = "; ".join(rule["implemented_evidence"]).replace("|", "\\|")
        false_negative = "; ".join(rule["known_false_negative_risks"]).replace("|", "\\|")
        question = "; ".join(rule["official_questions"]).replace("|", "\\|")
        next_test = rule["next_test_priority"].replace("|", "\\|")
        lines.append(
            f"| {rule['rule_id']} | `{rule['status']}` | {evidence} | {false_negative} | {question} | {next_test} |"
        )
    lines += [
        "",
        "## Cross-cutting priorities",
        "",
        "| Priority | Gap | Rules | Required change |",
        "|---|---|---|---|",
    ]
    for gap in payload["cross_cutting_gaps"]:
        lines.append(
            f"| `{gap['priority']}` | {gap['gap']} | {', '.join(gap['affected_rules'])} | {gap['required_change']} |"
        )
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "- `IMPLEMENTED_SYNTHETIC_UNCALIBRATED` means the synthetic predicate is implemented, not that official behavior is known.",
        "- `IMPLEMENTED_CONTEXT_DEPENDENT` requires a verified node/document-role mapping before a finding is reliable.",
        "- `PARTIAL_HEURISTIC` is intentionally incomplete and must remain visible in reports.",
        "- `BLOCKED_OFFICIAL_BEHAVIOR` requires real V1.1.0 observations before detector semantics can be frozen.",
        "- Official observations remain `0 / NOT_RUN`.",
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    report = {
        "status": "PASS",
        "rules": 26,
        "status_counts": dict(counts),
        "cross_cutting_gaps": len(payload["cross_cutting_gaps"]),
        "official_observations": 0,
    }
    build = ROOT / "build" / "p0-b1-detector-gap-register.json"
    build.parent.mkdir(parents=True, exist_ok=True)
    build.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
