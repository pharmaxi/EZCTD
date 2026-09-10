from __future__ import annotations

"""Evidence finalizer with reached/not-reached gate accounting.

A transaction can fail after binary identity, fixture identity, and outbound
isolation have already been proved.  The v1 finalizer relied only on the
``admissibility`` object written at the end of a successful transaction, so an
early UI failure made those upstream facts appear false.  This launcher derives
independent gates from the preserved runtime evidence before invoking the v1
conservation logic, then emits tri-state diagnostics without incrementing any
observation counter unless every mandatory gate passes.
"""

import json
import sys
from pathlib import Path
from typing import Any

import finalize_cde_validator_transaction_evidence as legacy


def _arg_path(flag: str) -> Path:
    try:
        return Path(sys.argv[sys.argv.index(flag) + 1])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"missing required argument {flag}") from exc


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _identity_gate(report: dict[str, Any]) -> bool:
    identity = report.get("identity") or {}
    hashes = {
        str(identity.get("alias_sha256") or "").lower(),
        str(identity.get("original_sha256") or "").lower(),
        str(identity.get("expected_sha256") or "").lower(),
    }
    return bool(
        identity.get("byte_identical")
        and identity.get("samefile")
        and len(hashes) == 1
        and "" not in hashes
    )


def _input_identity_gate(report: dict[str, Any]) -> bool:
    data = report.get("input") or {}
    before = str(data.get("inventory_digest_before") or "")
    expected = str(data.get("expected_inventory_digest") or "")
    return bool(before and expected and before == expected)


def _native_terminal_gate(report: dict[str, Any]) -> bool:
    native = report.get("native_result") or {}
    return bool(
        native.get("native_report_present")
        or native.get("terminal_alert")
        or native.get("table_native_texts")
    )


def _precondition_only(report: dict[str, Any]) -> bool | None:
    native = report.get("native_result")
    if not isinstance(native, dict):
        return None
    terminal = bool(
        native.get("native_report_present")
        or native.get("terminal_alert")
        or native.get("table_native_texts")
    )
    if not terminal:
        return None
    existing = (report.get("admissibility") or {}).get("precondition_only_result")
    if existing is not None:
        return bool(existing)
    alert = native.get("terminal_alert") or {}
    texts = alert.get("texts") or []
    joined = "\n".join(str(item) for item in texts)
    return any(
        term in joined
        for term in (
            "请选择申报资料",
            "请选择报告输出路径",
            "不规范的资料路径",
            "序列文件夹不是数字",
        )
    ) and not bool(native.get("native_report_present"))


def _seed_reached_gates(transaction: Path) -> None:
    report = _read(transaction)
    admissibility = report.setdefault("admissibility", {})
    admissibility["official_binary_identity_fixed"] = _identity_gate(report)
    admissibility["input_identity_fixed"] = _input_identity_gate(report)
    admissibility["outbound_firewall_ready"] = bool(
        (report.get("safety") or {}).get("firewall_ready")
    )
    admissibility["validation_control_invoked"] = bool(report.get("validation_invoked"))
    admissibility["native_terminal_result_captured"] = _native_terminal_gate(report)
    precondition = _precondition_only(report)
    admissibility["precondition_only_result"] = precondition
    input_data = report.get("input") or {}
    admissibility["input_unchanged"] = bool(input_data.get("unchanged"))
    admissibility["raw_evidence_written"] = transaction.exists()
    report["admissibility"] = admissibility
    _write(transaction, report)


def _state(value: bool | None, *, reached: bool = True) -> str:
    if not reached:
        return "NOT_REACHED"
    return "PASS" if bool(value) else "FAIL"


def _postprocess(transaction: Path, output_root: Path) -> None:
    report = _read(transaction)
    admissibility = report.get("admissibility") or {}
    validation_invoked = bool(report.get("validation_invoked"))
    terminal_reached = _native_terminal_gate(report)
    input_after_present = bool(
        (report.get("input") or {}).get("inventory_digest_after") is not None
    )
    precondition = admissibility.get("precondition_only_result")

    diagnostics = {
        "schema_version": "0.1.0",
        "semantics": {
            "PASS": "The gate is positively supported by preserved evidence.",
            "FAIL": "The stage was reached and the gate failed.",
            "NOT_REACHED": "The transaction stopped before this gate could be evaluated.",
        },
        "gates": {
            "official_binary_identity_fixed": {
                "state": _state(admissibility.get("official_binary_identity_fixed")),
                "source": "identity.byte_identical + identity.samefile + pinned hash equality",
            },
            "input_identity_fixed": {
                "state": _state(admissibility.get("input_identity_fixed")),
                "source": "input.inventory_digest_before == input.expected_inventory_digest",
            },
            "outbound_firewall_ready": {
                "state": _state(admissibility.get("outbound_firewall_ready")),
                "source": "safety.firewall_ready",
            },
            "validation_control_invoked": {
                "state": _state(
                    admissibility.get("validation_control_invoked"),
                    reached=validation_invoked,
                ),
                "source": "validation_invoked and action trace",
            },
            "native_terminal_result_captured": {
                "state": _state(
                    admissibility.get("native_terminal_result_captured"),
                    reached=validation_invoked,
                ),
                "source": "native report, native terminal dialog, or native table result",
            },
            "not_precondition_only": {
                "state": (
                    "NOT_REACHED"
                    if not terminal_reached or precondition is None
                    else ("FAIL" if bool(precondition) else "PASS")
                ),
                "source": "official terminal text classification",
            },
            "input_unchanged": {
                "state": _state(
                    admissibility.get("input_unchanged"),
                    reached=input_after_present,
                ),
                "source": "before/after fixture inventory digest",
            },
            "native_evidence_conserved": {
                "state": _state(
                    admissibility.get("native_evidence_conserved"),
                    reached=terminal_reached,
                ),
                "source": "native output or terminal UI copied into the immutable artifact",
            },
        },
    }
    pass_gates = [key for key, value in diagnostics["gates"].items() if value["state"] == "PASS"]
    failed_gates = [key for key, value in diagnostics["gates"].items() if value["state"] == "FAIL"]
    not_reached = [key for key, value in diagnostics["gates"].items() if value["state"] == "NOT_REACHED"]
    diagnostics.update(
        {
            "pass_gates": pass_gates,
            "failed_gates": failed_gates,
            "not_reached_gates": not_reached,
            "all_mandatory_gates_pass": not failed_gates and not not_reached,
        }
    )

    report["admissibility_gate_diagnostics"] = diagnostics
    report["failed_admissibility_gates"] = failed_gates
    report["not_reached_admissibility_gates"] = not_reached
    report["unmet_admissibility_gates"] = failed_gates + not_reached
    report.setdefault("assertions", {})["official_black_box_observation_count"] = int(
        (report.get("observation_counters") or {}).get("official_black_box_observations", 0)
    )
    _write(transaction, report)
    _write(output_root / "ADMISSIBILITY_GATE_DIAGNOSTICS.json", diagnostics)

    summary_path = output_root / "FINALIZED_TRANSACTION_SUMMARY.json"
    summary = _read(summary_path) if summary_path.exists() else {}
    summary["passed_admissibility_gates"] = pass_gates
    summary["failed_admissibility_gates"] = failed_gates
    summary["not_reached_admissibility_gates"] = not_reached
    summary["unmet_admissibility_gates"] = failed_gates + not_reached
    _write(summary_path, summary)


if __name__ == "__main__":
    transaction_path = _arg_path("--transaction")
    output_root_path = _arg_path("--output-root")
    _seed_reached_gates(transaction_path)
    exit_code = legacy.main()
    _postprocess(transaction_path, output_root_path)
    raise SystemExit(exit_code)
