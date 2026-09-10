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

WORKFLOWS = [
    ("converge-p0-agent-loop-v2.yml", "all local/synthetic/read-only contracts", "local-core"),
    ("finalize-p0-b0-v2.yml", "corrected P0-B0 fixture gate", "diagnostic"),
    ("p0-b1-readonly-observer-v2.yml", "P0-B1 read-only observer", "diagnostic"),
    ("p0-b1-package-inspector-v2.yml", "candidate package inspector", "diagnostic"),
    ("p0-b1-applicability-contract.yml", "rule applicability contract", "diagnostic"),
    ("p0-b0-calibration-evidence-contract.yml", "official-run evidence contract", "diagnostic"),
    ("manual-asset-import-contract.yml", "manual official-asset intake contract", "diagnostic"),
    ("p0-b0-sample-isolation-audit.yml", "target-positive isolation/correlation audit", "diagnostic"),
    ("regulatory-source-snapshot.yml", "CDE/ICH source snapshot", "external-evidence"),
    ("windows-validator-asset-inspection.yml", "Windows static asset inspection", "external-evidence"),
    ("analyze-ectd-technical-packages.yml", "technical package analysis", "external-evidence"),
    ("open-source-reference-inventory.yml", "open-source inventory", "external-research"),
    ("repair-regulatory-evidence-ledger.yml", "corrected evidence ledger", "external-evidence"),
]

MARKERS = [
    "docs/validation/p0-b0/P0_B0_ALL_LOCAL_GATES.md",
    "docs/validation/p0-b1/P0_B1_ALL_LOCAL_GATES.md",
    "docs/validation/p0-b0/SAMPLE_ISOLATION_AUDIT.md",
    "docs/validation/p0-b0/CALIBRATION_EVIDENCE_CONTRACT_GATE.md",
    "docs/validation/p0-b0/MANUAL_ASSET_INTAKE_GATE.md",
    "docs/validation/p0-b1/P0_B1_PACKAGE_INSPECTOR_GATE.md",
    "docs/validation/p0-b1/P0_B1_APPLICABILITY_GATE.md",
    "docs/status/P0_AGENT_LOOP_CONVERGENCE_V2.json",
]


def api(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "EZCTD-P0-status-v4/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def latest_run(workflow: str) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"branch": BRANCH, "per_page": 1})
    payload = api(f"/repos/{REPOSITORY}/actions/workflows/{workflow}/runs?{query}")
    runs = payload.get("workflow_runs", [])
    return runs[0] if runs else None


def pull_branch() -> None:
    subprocess.run(["git", "pull", "--rebase", "origin", BRANCH], check=True)


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def latest_open_pr() -> dict[str, Any] | None:
    owner = REPOSITORY.split("/", 1)[0]
    query = urllib.parse.urlencode({"state": "open", "head": f"{owner}:{BRANCH}", "base": "main", "per_page": 10})
    pulls = api(f"/repos/{REPOSITORY}/pulls?{query}")
    return pulls[0] if pulls else None


def main() -> int:
    states: list[dict[str, Any]] = []
    for _ in range(80):
        states = []
        for workflow, role, group in WORKFLOWS:
            try:
                run = latest_run(workflow)
            except Exception as exc:
                states.append({"workflow": workflow, "role": role, "group": group, "state": "API_ERROR", "error": f"{type(exc).__name__}: {exc}"})
                continue
            if run is None:
                states.append({"workflow": workflow, "role": role, "group": group, "state": "NOT_FOUND"})
                continue
            states.append(
                {
                    "workflow": workflow,
                    "role": role,
                    "group": group,
                    "state": "FOUND",
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "head_sha": run.get("head_sha"),
                    "run_id": run.get("id"),
                    "run_number": run.get("run_number"),
                    "html_url": run.get("html_url"),
                    "updated_at": run.get("updated_at"),
                }
            )
        convergence = next((item for item in states if item["workflow"] == "converge-p0-agent-loop-v2.yml"), None)
        if convergence and convergence.get("status") not in {"queued", "in_progress", "waiting", "pending", "requested"}:
            break
        time.sleep(15)

    pull_branch()
    convergence_report = load(Path("docs/status/P0_AGENT_LOOP_CONVERGENCE_V2.json"))
    marker_status = {path: Path(path).is_file() for path in MARKERS}
    convergence_state = next((item for item in states if item["workflow"] == "converge-p0-agent-loop-v2.yml"), {})
    local_pass = (
        convergence_state.get("conclusion") == "success"
        and convergence_report.get("status") == "PASS_ALL_LOCAL_CONTRACTS"
        and all(marker_status.values())
    )
    official = convergence_report.get("official_validator") or {}
    official_status = str(official.get("status") or "NOT_RUN")
    official_observations = int(official.get("observations") or 0)
    if official_status != "NOT_RUN" or official_observations != 0:
        # This collector does not trust a local convergence report as proof of an official run.
        # Official evidence must be imported and summarized through the dedicated evidence path.
        official_status = "UNVERIFIED_CLAIM_REQUIRES_EVIDENCE_IMPORT"

    try:
        pr = latest_open_pr()
    except Exception as exc:
        pr = None
        pr_error = f"{type(exc).__name__}: {exc}"
    else:
        pr_error = None

    payload = {
        "schema_version": "0.4.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": REPOSITORY,
        "branch": BRANCH,
        "local_contracts": "PASS" if local_pass else "INCOMPLETE_OR_FAILED",
        "official_cde_validator": {
            "target_version": "1.1.0",
            "status": official_status,
            "observations": official_observations,
        },
        "draft_pull_request": (
            {
                "present": True,
                "number": pr.get("number"),
                "title": pr.get("title"),
                "draft": pr.get("draft"),
                "html_url": pr.get("html_url"),
                "head_sha": (pr.get("head") or {}).get("sha"),
            }
            if pr
            else {"present": False, "error": pr_error}
        ),
        "convergence_report_status": convergence_report.get("status"),
        "markers": marker_status,
        "workflows": states,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "P0_AUTOMATION_STATUS_V4.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sentinel = [
        f"LOCAL_CONTRACTS={payload['local_contracts']}",
        f"OFFICIAL_CDE_VALIDATOR={official_status}",
        f"OFFICIAL_OBSERVATIONS={official_observations}",
        f"DRAFT_PR_PRESENT={str(payload['draft_pull_request']['present']).lower()}",
        f"DRAFT_PR_NUMBER={payload['draft_pull_request'].get('number') or ''}",
        f"BRANCH={BRANCH}",
        f"CONVERGENCE_WORKFLOW={convergence_state.get('conclusion') or convergence_state.get('status') or 'not-found'}",
    ]
    (OUT / "P0_SENTINEL.txt").write_text("\n".join(sentinel) + "\n", encoding="utf-8")

    lines = [
        "# P0 automation status v4",
        "",
        f"- Local/synthetic/read-only contracts: **{payload['local_contracts']}**",
        f"- Official CDE V1.1.0: **{official_status}**, observations: **{official_observations}**",
        f"- Draft PR present: **{payload['draft_pull_request']['present']}**",
        "",
        "## Workflow states",
        "",
        "| Workflow | Group | Status | Conclusion | Head SHA | Run |",
        "|---|---|---|---|---|---|",
    ]
    for state in states:
        url = state.get("html_url")
        run = f"[open]({url})" if url else "—"
        lines.append(
            f"| `{state['workflow']}` | {state['group']} | {state.get('status') or state.get('state')} | "
            f"{state.get('conclusion') or '—'} | `{state.get('head_sha') or '—'}` | {run} |"
        )
    lines += [
        "",
        "External evidence workflows are reported independently. Their failure does not erase a valid local contract gate, and their success does not establish official compatibility.",
        "",
    ]
    (OUT / "P0_AUTOMATION_STATUS_V4.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(sentinel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
