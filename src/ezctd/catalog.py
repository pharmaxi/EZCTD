from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleMetadata:
    rule_id: str
    title: str
    severity: str
    official_explanation: str
    scope_exemptions: tuple[str, ...]
    source_page: int


class RuleCatalog:
    def __init__(self, rules: dict[str, RuleMetadata], profile_id: str) -> None:
        self.rules = rules
        self.profile_id = profile_id

    @classmethod
    def from_json(cls, path: Path) -> "RuleCatalog":
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        rules: dict[str, RuleMetadata] = {}
        for item in payload["rules"]:
            rule = RuleMetadata(
                rule_id=item["id"],
                title=item["official_title"],
                severity=item["official_severity"],
                official_explanation=item["official_explanation"],
                scope_exemptions=tuple(item.get("scope_exemptions", [])),
                source_page=int(item["printed_page"]),
            )
            rules[rule.rule_id] = rule
        expected = [f"6.{number}" for number in range(1, 27)]
        if list(rules) != expected:
            raise ValueError(f"official rule catalog is not ordered 6.1–6.26: {list(rules)}")
        counts: dict[str, int] = {}
        for rule in rules.values():
            counts[rule.severity] = counts.get(rule.severity, 0) + 1
        if counts != {"错误": 16, "警告": 8, "提示信息": 2}:
            raise ValueError(f"unexpected official severity counts: {counts}")
        return cls(rules, payload["profile_id"])

    def get(self, rule_id: str) -> RuleMetadata:
        return self.rules[rule_id]
