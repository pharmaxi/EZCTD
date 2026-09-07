from __future__ import annotations

from dataclasses import dataclass

from .models import PdfContext

REFERENCE_NODES = {"2.7.5", "3.3", "4.3", "5.4"}
FAST_WEB_VIEW_EXEMPT_NODES = {"1.0", "1.2", "1.3.8", "1.10", "1.11", "1.12"} | REFERENCE_NODES
REFERENCE_EXEMPT_RULES = {f"6.{number}" for number in range(2, 21)} | {"6.24", "6.25", "6.26"}


@dataclass(frozen=True, slots=True)
class Applicability:
    applicable: bool
    reason: str
    known: bool = True


def _is_foreign_reference(context: PdfContext) -> bool:
    role = (context.document_role or "").strip().lower()
    language = (context.language or "").strip().lower()
    return role in {"reference", "literature-reference", "foreign-reference"} and language not in {
        "",
        "zh",
        "zh-cn",
        "zh-hans",
        "chinese",
    }


def _is_reference_context(context: PdfContext) -> bool:
    return (context.node_id or "") in REFERENCE_NODES or _is_foreign_reference(context)


def resolve(rule_id: str, context: PdfContext) -> Applicability:
    node = (context.node_id or "").strip()
    role = (context.document_role or "").strip().lower()

    if rule_id in REFERENCE_EXEMPT_RULES and _is_reference_context(context):
        return Applicability(False, "official reference/foreign-reference exemption")

    if rule_id == "6.22" and (any(node == item or node.startswith(item + ".") for item in FAST_WEB_VIEW_EXEMPT_NODES) or _is_reference_context(context)):
        return Applicability(False, "official Fast Web View node/reference exemption")

    if rule_id == "6.23":
        if _is_reference_context(context):
            return Applicability(False, "official reference/foreign-reference exemption")
        if node == "1.2" or role in {"application-form", "application"}:
            return Applicability(False, "official application-form exemption")

    if rule_id not in {"6.1", "6.21"} and (not node or not context.language):
        return Applicability(True, "partial CRO context; node or language not confirmed", known=False)
    return Applicability(True, "no implemented exemption matched")
