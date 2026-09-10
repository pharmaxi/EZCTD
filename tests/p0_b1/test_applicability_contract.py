from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ezctd.applicability import FAST_WEB_VIEW_EXEMPT_NODES, REFERENCE_EXEMPT_RULES, REFERENCE_NODES, resolve
from ezctd.models import PdfContext


def context(*, node_id: str | None = None, role: str | None = None, language: str | None = None) -> PdfContext:
    root = ROOT / "build" / "applicability-placeholder"
    return PdfContext(root / "leaf.pdf", root, node_id=node_id, document_role=role, language=language)


def main() -> int:
    all_rules = {f"6.{number}" for number in range(1, 27)}
    expected_reference = {f"6.{number}" for number in range(2, 21)} | {"6.24", "6.25", "6.26"}
    assert REFERENCE_EXEMPT_RULES == expected_reference
    assert REFERENCE_NODES == {"2.7.5", "3.3", "4.3", "5.4"}
    assert FAST_WEB_VIEW_EXEMPT_NODES == {"1.0", "1.2", "1.3.8", "1.10", "1.11", "1.12", "2.7.5", "3.3", "4.3", "5.4"}

    checks = []
    for node in sorted(REFERENCE_NODES):
        ctx = context(node_id=node, role="reference", language="zh-CN")
        not_applicable = {rule for rule in all_rules if not resolve(rule, ctx).applicable}
        expected = expected_reference | {"6.22", "6.23"}
        assert not_applicable == expected, (node, not_applicable, expected)
        checks.append({"context": f"reference-node-{node}", "not_applicable": sorted(not_applicable)})

    foreign = context(node_id="5.3.5", role="foreign-reference", language="en")
    foreign_not_applicable = {rule for rule in all_rules if not resolve(rule, foreign).applicable}
    assert foreign_not_applicable == expected_reference | {"6.22", "6.23"}
    checks.append({"context": "foreign-reference", "not_applicable": sorted(foreign_not_applicable)})

    chinese_reference_role = context(node_id="5.3.5", role="reference", language="zh-CN")
    assert all(resolve(rule, chinese_reference_role).applicable for rule in all_rules)
    checks.append({"context": "chinese-reference-role-outside-reference-node", "not_applicable": []})

    application_form = context(node_id="1.2", role="application-form", language="zh-CN")
    app_not_applicable = {rule for rule in all_rules if not resolve(rule, application_form).applicable}
    assert app_not_applicable == {"6.22", "6.23"}
    checks.append({"context": "application-form", "not_applicable": sorted(app_not_applicable)})

    for node in sorted(FAST_WEB_VIEW_EXEMPT_NODES - REFERENCE_NODES):
        ctx = context(node_id=node, role="submission-document", language="zh-CN")
        assert not resolve("6.22", ctx).applicable
        if node == "1.2":
            assert not resolve("6.23", ctx).applicable
        else:
            assert resolve("6.23", ctx).applicable
        assert resolve("6.1", ctx).applicable
        checks.append({"context": f"fast-web-node-{node}", "not_applicable": ["6.22"] + (["6.23"] if node == "1.2" else [])})

    ordinary = context(node_id="5.3.5", role="study-report", language="zh-CN")
    assert all(resolve(rule, ordinary).applicable for rule in all_rules)
    checks.append({"context": "ordinary-study-report", "not_applicable": []})

    report = {"schema_version": "0.1.0", "status": "PASS", "checks": checks}
    output = ROOT / "build" / "p0-b1-applicability-contract.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "contexts": len(checks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
