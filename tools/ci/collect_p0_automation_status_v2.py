from __future__ import annotations

import importlib.util
from pathlib import Path

source = Path(__file__).with_name("collect_p0_automation_status.py")
spec = importlib.util.spec_from_file_location("collect_p0_status_base", source)
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load base P0 status collector")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.TARGETS = [
    {"file": "finalize-p0-b0-v2.yml", "role": "corrected success-only synthetic gate", "core": True},
    {"file": "p0-b0-validation.yml", "role": "repeatable full synthetic validation", "core": True},
    {"file": "regulatory-source-snapshot.yml", "role": "CDE/ICH source snapshot", "core": False},
    {"file": "windows-validator-asset-inspection.yml", "role": "Windows static validator asset inspection", "core": False},
    {"file": "open-source-reference-inventory.yml", "role": "open-source reference inventory", "core": False},
    {"file": "analyze-ectd-technical-packages.yml", "role": "eCTD technical package analysis", "core": False},
]
raise SystemExit(module.main())
