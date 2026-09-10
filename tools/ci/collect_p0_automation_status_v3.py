from __future__ import annotations

import importlib.util
from pathlib import Path

source = Path(__file__).with_name("collect_p0_automation_status.py")
spec = importlib.util.spec_from_file_location("collect_p0_status_base_v3", source)
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load base P0 status collector")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.TARGETS = [
    {"file": "finalize-p0-b0-v2.yml", "role": "corrected P0-B0 success-only synthetic gate", "core": True},
    {"file": "p0-b1-readonly-observer-v2.yml", "role": "P0-B1 target coverage and byte-level read-only gate", "core": True},
    {"file": "p0-b0-sample-isolation-audit.yml", "role": "target-positive isolation/correlation audit", "core": True},
    {"file": "regulatory-source-snapshot.yml", "role": "CDE/ICH source snapshot", "core": False},
    {"file": "windows-validator-asset-inspection.yml", "role": "Windows static validator asset inspection", "core": False},
    {"file": "open-source-reference-inventory.yml", "role": "open-source reference inventory", "core": False},
    {"file": "analyze-ectd-technical-packages.yml", "role": "eCTD technical package analysis", "core": False},
    {"file": "regulatory-evidence-completeness.yml", "role": "regulatory evidence completeness ledger", "core": False},
]
module.EXPECTED_FILES = [
    "docs/validation/p0-b0/CI_GATE_PASS.md",
    "docs/validation/p0-b0/SAMPLE_ISOLATION_AUDIT.md",
    "docs/validation/p0-b0/RULE_VALIDATION_MATRIX.md",
    "docs/validation/p0-b0/OFFICIAL_VALIDATOR_BLACKBOX_PROTOCOL.md",
    "tests/p0_b0/case_matrix.json",
    "tests/p0_b0/smoke_manifest.json",
    "tests/p0_b0/smoke_expectations.json",
    "tests/p0_b0/boundary_experiment_queue.json",
    "docs/validation/p0-b1/P0_B1_OBSERVER_GATE.md",
    "src/ezctd/pdf_observer.py",
    "tools/cde-validator/capture-validator-run.ps1",
    "evidence/regulatory/snapshots/cde-2026-v1.1/manifest.json",
    "evidence/regulatory/snapshots/cde-validator-v1.1.0/inspection.json",
    "evidence/regulatory/snapshots/ectd-package-analysis/analysis.json",
    "evidence/regulatory/P0_REGULATORY_EVIDENCE_COMPLETENESS.json",
    "docs/research/open-source/inventory.json",
]
raise SystemExit(module.main())
