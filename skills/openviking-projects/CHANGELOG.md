# Changelog

## 1.0.2 — 2026-10-20

- Initial public release, based on the audited portable runtime.
- Support mirrored and offline installation, model probes, reviewed source selection, and incremental project sync.
- Use one global `openviking` MCP with explicit project/workspace routing and independent accounts by default.
- Reject unknown bootstrap parameters and invalid source policies before project registration.
- Make Git provenance optional, handle nested Markdown code fences, isolate pip installation settings, and check runtime compatibility before installation.
- Publish global MCP configuration atomically and preserve changes made during registration.
- Include opt-in login startup, weekday scheduling, and 19 offline regression checks.
