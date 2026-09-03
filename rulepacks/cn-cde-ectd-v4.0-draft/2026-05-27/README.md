# China eCTD v4.0 consultation package — isolated research register

> Status: **DRAFT / RESEARCH ONLY**. Published for consultation on 2026-05-27. It must not affect the effective China eCTD V3.2.2/V1.1 validator profile.

## Retrieved attachments

| Source ID | Role | Kind | Pages | SHA-256 |
|---|---|---:|---:|---|

## Product architecture decision

- Use a separate profile namespace: `cn-cde-ectd-v4.0-draft/2026-05-27`.
- Do not translate v4.0 validation messages into current 6.1–6.26 detector behavior.
- Reuse only neutral infrastructure: source ledger, XML parser, package graph, controlled-vocabulary loader, evidence reports and worker isolation.
- Keep models extensible for UUIDs, document reuse/reference, context-of-use and controlled keywords without changing current V3.2.2 output.
- Perform a new formal delta when final China v4.0 implementation documents are published.

## Automatically located v4 concepts
