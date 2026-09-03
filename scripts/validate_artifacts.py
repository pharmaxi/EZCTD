#!/usr/bin/env python3
"""Validate the EZCTD planning baseline using only the standard library."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/prd/RegPDF_Workbench_CDE_eCTD_PRD_v0.1.md"
RULES = ROOT / "rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_draft.json"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    for path in (PRD, RULES):
        if not path.is_file():
            fail(f"missing required artifact: {path.relative_to(ROOT)}")
        if path.stat().st_size == 0:
            fail(f"artifact is empty: {path.relative_to(ROOT)}")

    if not PRD.read_bytes().startswith(b"# RegPDF Workbench"):
        fail("unexpected PRD title or encoding")

    try:
        doc = json.loads(RULES.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"rule JSON cannot be parsed: {exc}")

    rules = doc.get("rules")
    if not isinstance(rules, list):
        fail("rule JSON field 'rules' must be a list")
    if len(rules) != 26:
        fail(f"expected 26 rules, found {len(rules)}")

    ids = [rule.get("id") for rule in rules]
    if any(not isinstance(rule_id, str) or not rule_id.strip() for rule_id in ids):
        fail("every rule must have a non-empty string id")
    if len(set(ids)) != len(ids):
        fail("rule ids are not unique")

    if doc.get("profile_id") != "cde-ectd-v3.2.2-cn-v1.1":
        fail("unexpected profile_id")

    print("EZCTD planning baseline validation passed")
    print(f"  Rules: {len(rules)} unique entries")
    print(f"  Profile: {doc['profile_id']}")


if __name__ == "__main__":
    main()
