from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVER_GATE = ROOT / "tests" / "p0_b1" / "run_smoke_observer.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_readonly_gate.py <generated-smoke-directory>")
    smoke_dir = Path(sys.argv[1]).resolve()
    files = sorted(smoke_dir.glob("*.pdf"))
    if len(files) != 28:
        raise SystemExit(f"expected 28 smoke PDFs, got {len(files)}")
    before = {path.name: sha256(path) for path in files}
    subprocess.run([sys.executable, str(OBSERVER_GATE), str(smoke_dir)], check=True)
    after = {path.name: sha256(path) for path in files}
    changed = [name for name in before if before[name] != after[name]]
    report = {
        "schema_version": "0.1.0",
        "files": len(files),
        "unchanged": len(files) - len(changed),
        "changed": changed,
        "status": "PASS" if not changed else "FAIL",
    }
    output = ROOT / "build" / "p0-b1-readonly-integrity.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
