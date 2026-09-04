from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def load_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "tools/regulatory/analyze_cde_validator_sequence_folder_probe.py"
    )
    spec = importlib.util.spec_from_file_location(
        "analyze_cde_validator_sequence_folder_probe", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_probe_classifies_warning_persistence_without_claiming_calibration(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    transaction = tmp_path / "transaction.json"
    native = tmp_path / "native.json"
    control = tmp_path / "control.json"
    output = tmp_path / "comparison.json"
    markdown = tmp_path / "comparison.md"

    dump(
        transaction,
        {
            "run_id": "probe-0001-run",
            "case_id": "cn-v11-probe-001-invalid-empty-root-0001",
            "status": "ADMISSIBLE_ENVIRONMENT_ADAPTED_OFFICIAL_OBSERVATION",
            "admissible_official_black_box_observation": True,
            "validation_invoked": True,
            "input": {"directory": "C:/EZCTDProbeInput/0001", "unchanged": True},
            "native_result": {
                "native_report_present": True,
                "terminal_alert": {"texts": ["提示", "执行成功", "OK"]},
            },
            "action_trace": [
                {
                    "action": "confirm_native_dialog",
                    "button": "OK",
                    "texts": [
                        "Warning",
                        "不规范的资料路径",
                        "序列文件夹不是数字。仍要使用？",
                        "OK",
                    ],
                }
            ],
        },
    )
    dump(
        native,
        {
            "rule_count": 151,
            "summary": {"totals": {"提示信息": 5, "警告": 22, "错误": 96}},
            "metadata": {"序列号": "缺失区域性骨架文件！"},
            "normalization": {
                "normalized_visible_text_sha256": "visible",
                "semantic_contract_sha256": "semantic",
            },
        },
    )
    dump(
        control,
        {
            "case": {"case_id": "cn-v11-probe-000-invalid-empty-root"},
            "observations": [
                {
                    "semantic_summary": {
                        "visible_rule_count": 151,
                        "severity_totals": {"提示信息": 5, "警告": 22, "错误": 96},
                    }
                }
            ],
            "stability_assessment": {
                "observation_count": 3,
                "same_pre_validation_warning": True,
            },
        },
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--transaction",
            str(transaction),
            "--native-summary",
            str(native),
            "--control-stability",
            str(control),
            "--json",
            str(output),
            "--markdown",
            str(markdown),
        ],
    )
    assert module.main() == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["conclusion"] == "WARNING_PERSISTS_WITH_0001"
    assert result["comparison"]["same_rule_count_as_control"] is True
    assert result["comparison"]["same_severity_totals_as_control"] is True
    assert result["counters"] == {
        "official_black_box_observation_increment_if_admissible": 1,
        "calibration_informative_observation_increment": 0,
    }
    assert markdown.exists()
