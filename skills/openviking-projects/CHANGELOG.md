# Changelog

## 1.1.1 — 2026-11-09

- Run chat-triggered synchronization in a detached worker with a run ID and duplicate-start protection. Keep the existing system clock foreground entrypoint.
- Persist interrupted/failed receipts and stream child logs immediately; terminate only owned child process groups on signal or timeout, leaving server-side imports for journal reconciliation.
- Archive prior receipts byte-for-byte. Status queries reconcile stale running receipts only after the run lock is free; interrupted runs never automatically resubmit work.
- Add real-process regressions for signals, forced termination, timeout, starter exit and aggregate/project interruption state.
- Preserve opt-in Studio, project scope, credentials, parser and incremental change limits.

## 1.1.0 — 2026-11-08

- Bundle the enhanced local Studio as an optional component, activated for monitoring, Web dashboard and advanced-Studio requests. Ordinary installation and project onboarding do not deploy or start it.
- Add `studio install/start/status/stop/install-entry/restore-entry`, configurable loopback ports, deployment fingerprints, instance identity checks, and reversible original-Studio entry replacement.
- Include project freshness, source previews, read-only sync preflight, task pagination, model/Token usage, snapshot-aware retrieval and service-wide events. Reuse the local registry and credentials without bundling machine-specific data.
- Carry over reviewed fixes for filtering, failed pagination retries, stale responses, partial failures, history navigation and mobile controls; add portable deployment and custom-port regressions.

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
