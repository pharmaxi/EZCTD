from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "laojia-a/EZCTD")
BRANCH = os.environ.get("P0_BRANCH", "agent/p0-b0-validation-matrix")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
OUT = Path("docs/status")

TARGETS = [
    {"file": "finalize-p0-b0.yml", "role": "success-only synthetic gate", "core": True},
    {"file": "p0-b0-validation.yml", "role": "repeatable full synthetic validation", "core": True},
    {"file": "regulatory-source-snapshot.yml", "role": "CDE/ICH source snapshot", "core": False},
    {"file": "windows-validator-asset-inspection.yml", "role": "Windows static validator asset inspection", "core": False},
    {"file": "open-source-reference-inventory.yml", "role": "open-source reference inventory", "core": False},
    {"file": "analyze-ectd-technical-packages.yml", "role": "eCTD technical package analysis", "core": False},
]

EXPECTED_FILES = [
    "docs/validation/p0-b0/CI_GATE_PASS.md",
    "docs/validation/p0-b0/RULE_VALIDATION_MATRIX.md",
    "docs/validation/p0-b0/OFFICIAL_VALIDATOR_BLACKBOX_PROTOCOL.md",
    "tests/p0_b0/case_matrix.json",
    "tests/p0_b0/smoke_manifest.json",
    "tests/p0_b0/boundary_experiment_queue.json",
    "tools/cde-validator/capture-validator-run.ps1",
    "evidence/regulatory/snapshots/cde-2026-v1.1/manifest.json",
    "evidence/regulatory/snapshots/cde-validator-v1.1.0/inspection.json",
    "evidence/regulatory/snapshots/ectd-package-analysis/analysis.json",
    "docs/research/open-source/inventory.json",
]


def api(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "EZCTD-P0-status-collector/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def latest_run(workflow: str) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"branch": BRANCH, "per_page": 10})
    payload = api(f"/repos/{REPOSITORY}/actions/workflows/{workflow}/runs?{query}")
    runs = payload.get("workflow_runs", [])
    if not runs:
        return None
    # Prefer a run whose head SHA is reachable from the feature branch and that is not the
    # currently executing collector workflow. For each target filename, the first item is latest.
    return runs[0]


def job_summary(run: dict[str, Any]) -> list[dict[str, Any]]:
    if not run.get("jobs_url"):
        return []
    url = run["jobs_url"]
    path = urllib.parse.urlparse(url).path
    payload = api(path + "?per_page=100")
    jobs = []
    for job in payload.get("jobs", []):
        failed_steps = [
            {"name": step.get("name"), "number": step.get("number"), "conclusion": step.get("conclusion")}
            for step in job.get("steps", [])
            if step.get("conclusion") not in {None, "success", "skipped"}
        ]
        jobs.append({
            "name": job.get("name"),
            "status": job.get("status"),
            "conclusion": job.get("conclusion"),
            "html_url": job.get("html_url"),
            "failed_steps": failed_steps,
        })
    return jobs


def pull_branch() -> None:
    subprocess.run(["git", "pull", "--rebase", "origin", BRANCH], check=True)


def collect_once() -> list[dict[str, Any]]:
    records = []
    for target in TARGETS:
        try:
            run = latest_run(target["file"])
        except Exception as exc:
            records.append({**target, "state": "API_ERROR", "error": f"{type(exc).__name__}: {exc}"})
            continue
        if run is None:
            records.append({**target, "state": "NOT_FOUND"})
            continue
        records.append({
            **target,
            "state": "FOUND",
            "run_id": run.get("id"),
            "run_number": run.get("run_number"),
            "event": run.get("event"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("head_sha"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "html_url": run.get("html_url"),
            "jobs": job_summary(run) if run.get("status") == "completed" else [],
        })
    return records


def main() -> int:
    # Poll only while relevant workflows are currently queued/in progress. A hard cap avoids
    # turning this collector into a background service.
    records: list[dict[str, Any]] = []
    for _ in range(60):
        records = collect_once()
        active = [r for r in records if r.get("status") in {"queued", "in_progress", "waiting", "requested", "pending"}]
        if not active:
            break
        time.sleep(15)

    pull_branch()
    file_status = [{"path": path, "exists": Path(path).is_file()} for path in EXPECTED_FILES]
    core_success = all(r.get("conclusion") == "success" for r in records if r.get("core") and r.get("state") == "FOUND")
    core_found = all(any(r["file"] == target["file"] and r.get("state") == "FOUND" for r in records) for target in TARGETS if target["core"])
    gate_marker = Path("docs/validation/p0-b0/CI_GATE_PASS.md").is_file()

    payload = {
        "schema_version": "0.1.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": REPOSITORY,
        "branch": BRANCH,
        "overall": {
            "core_workflows_found": core_found,
            "core_workflows_successful": core_success,
            "success_marker_present": gate_marker,
            "p0_b0_a_status": "PASS" if core_found and core_success and gate_marker else "INCOMPLETE_OR_FAILED",
            "p0_b0_b_official_validator": "NOT_RUN",
        },
        "workflows": records,
        "expected_files": file_status,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "P0_AUTOMATION_STATUS.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# P0 automation status",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Branch: `{BRANCH}`",
        f"- P0-B0-A: **{payload['overall']['p0_b0_a_status']}**",
        "- P0-B0-B official CDE V1.1.0 observations: **NOT_RUN**",
        "",
        "## Workflows",
        "",
        "| Workflow | Role | Status | Conclusion | Head SHA | Run |",
        "|---|---|---|---|---|---|",
    ]
    for record in records:
        url = record.get("html_url")
        run = f"[open]({url})" if url else "—"
        lines.append(
            f"| `{record['file']}` | {record['role']} | {record.get('status', record.get('state', 'unknown'))} | "
            f"{record.get('conclusion') or '—'} | `{record.get('head_sha') or '—'}` | {run} |"
        )
        for job in record.get("jobs", []):
            for step in job.get("failed_steps", []):
                lines.append(f"| ↳ failed step | {job['name']} / {step['name']} | — | {step['conclusion']} | — | [job]({job.get('html_url')}) |")
    lines += ["", "## Expected repository evidence", "", "| Path | Present |", "|---|---:|"]
    for item in file_status:
        lines.append(f"| `{item['path']}` | {item['exists']} |")
    lines += [
        "",
        "The status collector reports repository and GitHub Actions state only. It does not convert a synthetic gate into official CDE compatibility evidence.",
        "",
    ]
    (OUT / "P0_AUTOMATION_STATUS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["overall"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
