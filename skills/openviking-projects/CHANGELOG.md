# Changelog

## 1.0.3 — 2026-11-07

- Reconcile a journaled task returning HTTP 404 only after refreshing the complete task inventory, rejecting active/overlapping tasks, and verifying every canonical original hash. Preserve other HTTP failures and never resubmit a missing task blindly.
- Read task inventory through bounded cursor pagination; reject malformed, incomplete or looping pages before submitting work.
- Include parser options in import job identities and propagate them through initial and incremental sync. Existing-index parser changes remain blocked pending separate review.
- Extend offline regressions from 19 to 32 checks and native integration with a real missing-task 404 plus zero-model-job recovery.
- Keep fresh initialization for unrelated projects, independent accounts, one global MCP, mirrored/offline installation and existing runtime preservation.

## 1.0.2 — 2026-10-20

- Initial public release, based on the audited portable runtime.
- Support mirrored and offline installation, model probes, reviewed source selection, and incremental project sync.
- Use one global `openviking` MCP with explicit project/workspace routing and independent accounts by default.
- Reject unknown bootstrap parameters and invalid source policies before project registration.
- Make Git provenance optional, handle nested Markdown code fences, isolate pip installation settings, and check runtime compatibility before installation.
- Publish global MCP configuration atomically and preserve changes made during registration.
- Include opt-in login startup, weekday scheduling, and 19 offline regression checks.
