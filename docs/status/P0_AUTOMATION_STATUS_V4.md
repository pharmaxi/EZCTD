# P0 automation status v4

- Local/synthetic/read-only contracts: **INCOMPLETE_OR_FAILED**
- Official CDE V1.1.0: **NOT_RUN**, observations: **0**
- Draft PR present: **False**

## Workflow states

| Workflow | Group | Status | Conclusion | Head SHA | Run |
|---|---|---|---|---|---|
| `converge-p0-agent-loop-v2.yml` | local-core | completed | failure | `13befee79e1cf7b305e32593461e7e31a97830cf` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33749377442) |
| `finalize-p0-b0-v2.yml` | diagnostic | completed | failure | `3cb52b4ee53a9f32334dd90ec6452b04e45ca845` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33749594341) |
| `p0-b1-readonly-observer-v2.yml` | diagnostic | completed | failure | `3cb52b4ee53a9f32334dd90ec6452b04e45ca845` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33749591375) |
| `p0-b1-package-inspector-v2.yml` | diagnostic | completed | failure | `3cb52b4ee53a9f32334dd90ec6452b04e45ca845` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33749595458) |
| `p0-b1-applicability-contract.yml` | diagnostic | completed | failure | `a91daccdfa60d831c8412c7c8804515827ca31ce` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33748791929) |
| `p0-b0-calibration-evidence-contract.yml` | diagnostic | completed | success | `4a9c00cfe024f3082c9816624d0e8bff8b588b6a` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33748873820) |
| `manual-asset-import-contract.yml` | diagnostic | completed | failure | `3cb52b4ee53a9f32334dd90ec6452b04e45ca845` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33749593367) |
| `p0-b0-sample-isolation-audit.yml` | diagnostic | completed | failure | `d652705c078eb0e1d20222f2394b25c654497052` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33746561121) |
| `regulatory-source-snapshot.yml` | external-evidence | completed | success | `6f9cd783291364fee4ce6b024672a42df05038f6` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33745096187) |
| `windows-validator-asset-inspection.yml` | external-evidence | completed | success | `fa1703f0a54747554231292f9662d70d6d8e15c7` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33745769322) |
| `analyze-ectd-technical-packages.yml` | external-evidence | completed | success | `c392e24314a45c78bc69817fa9294210fe2ebd1a` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33746178553) |
| `open-source-reference-inventory.yml` | external-research | completed | success | `472ecb026d975636df1396ccc2fee8113b293985` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33745681500) |
| `repair-regulatory-evidence-ledger.yml` | external-evidence | completed | success | `c9a6ddeb2c070cfe8ea0efaabb2da48f6808aeb6` | [open](https://github.com/laojia-a/EZCTD/actions/runs/33747978384) |

External evidence workflows are reported independently. Their failure does not erase a valid local contract gate, and their success does not establish official compatibility.
