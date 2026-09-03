# P0 automation status

- Generated: 2026-09-03T10:50:21.171645+00:00
- Branch: `agent/p0-b0-validation-matrix`
- P0-B0-A: **INCOMPLETE_OR_FAILED**
- P0-B0-B official CDE V1.1.0 observations: **NOT_RUN**

## Workflows

| Workflow | Role | Status | Conclusion | Head SHA | Run |
|---|---|---|---|---|---|
| `finalize-p0-b0-v2.yml` | corrected success-only synthetic gate | completed | failure | `bbf79b648bec923d672b78c349331621c6923d8a` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33746427385) |
| `p0-b0-validation.yml` | repeatable full synthetic validation | API_ERROR | — | `—` | — |
| `regulatory-source-snapshot.yml` | CDE/ICH source snapshot | completed | success | `6f9cd783291364fee4ce6b024672a42df05038f6` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33745096187) |
| `windows-validator-asset-inspection.yml` | Windows static validator asset inspection | completed | success | `fa1703f0a54747554231292f9662d70d6d8e15c7` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33745769322) |
| `open-source-reference-inventory.yml` | open-source reference inventory | completed | success | `472ecb026d975636df1396ccc2fee8113b293985` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33745681500) |
| `analyze-ectd-technical-packages.yml` | eCTD technical package analysis | completed | success | `c392e24314a45c78bc69817fa9294210fe2ebd1a` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33746178553) |

## Expected repository evidence

| Path | Present |
|---|---:|
| `docs/validation/p0-b0/CI_GATE_PASS.md` | False |
| `docs/validation/p0-b0/RULE_VALIDATION_MATRIX.md` | False |
| `docs/validation/p0-b0/OFFICIAL_VALIDATOR_BLACKBOX_PROTOCOL.md` | False |
| `tests/p0_b0/case_matrix.json` | False |
| `tests/p0_b0/smoke_manifest.json` | False |
| `tests/p0_b0/boundary_experiment_queue.json` | False |
| `tools/cde-validator/capture-validator-run.ps1` | False |
| `evidence/regulatory/snapshots/cde-2026-v1.1/manifest.json` | True |
| `evidence/regulatory/snapshots/cde-validator-v1.1.0/inspection.json` | True |
| `evidence/regulatory/snapshots/ectd-package-analysis/analysis.json` | True |
| `docs/research/open-source/inventory.json` | True |

The status collector reports repository and GitHub Actions state only. It does not convert a synthetic gate into official CDE compatibility evidence.
