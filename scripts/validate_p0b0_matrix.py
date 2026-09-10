from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tests/corpus/specs/cn-cde-ectd-v1.1/pdf-rules.json"


def fail(message: str) -> None:
    raise SystemExit(f"P0-B0 matrix invalid: {message}")


def main() -> None:
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    if len(rules) != 26:
        fail(f"expected 26 rules, got {len(rules)}")
    expected_ids = [f"6.{i}" for i in range(1, 27)]
    ids = [r.get("id") for r in rules]
    if ids != expected_ids:
        fail(f"rule order/IDs mismatch: {ids}")

    all_case_ids: list[str] = []
    classes = Counter()
    generator_status = Counter()
    for rule in rules:
        contract = rule.get("detector_contract") or {}
        for key in ("predicate", "required_context", "must_preserve_evidence"):
            if not contract.get(key):
                fail(f"{rule['id']} missing detector_contract.{key}")
        test_cases = rule.get("test_cases", [])
        if len(test_cases) < 4:
            fail(f"{rule['id']} has fewer than 4 cases")
        if not any(c.get("class") == "conformant" for c in test_cases):
            fail(f"{rule['id']} missing conformant case")
        if not any(c.get("class") in {"violation", "interaction", "boundary"} for c in test_cases):
            fail(f"{rule['id']} missing adverse/boundary case")
        for case in test_cases:
            cid = case.get("case_id")
            if not cid:
                fail(f"{rule['id']} has case without ID")
            all_case_ids.append(cid)
            classes[case.get("class")] += 1
            generator_status[case.get("generator_status")] += 1
            obs = case.get("expected_cde", {})
            if obs.get("observation_status") != "NOT_RUN" or obs.get("observed_state") is not None:
                fail(f"{cid} claims official observation before evidence is registered")

    if len(all_case_ids) != len(set(all_case_ids)):
        dupes = [k for k,v in Counter(all_case_ids).items() if v > 1]
        fail(f"duplicate case IDs: {dupes}")
    if len(all_case_ids) < 104:
        fail(f"expected at least 104 cases, got {len(all_case_ids)}")

    declared = data.get("counts", {})
    if declared.get("rules") != len(rules) or declared.get("cases") != len(all_case_ids):
        fail("declared counts do not match actual counts")

    print(json.dumps({
        "status": "PASS",
        "rules": len(rules),
        "cases": len(all_case_ids),
        "classes": dict(classes),
        "generator_status": dict(generator_status),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
