# Security Policy

## Supported Versions
| Version | Supported | Status |
| --- | :---: | --- |
| 1.0.x | :white_check_mark: | Active |

## Reporting a Vulnerability
Please report vulnerabilities responsibly to maintainers via private channels.
Do not open public issues for security vulnerabilities.

## Local deployment and dependency review (2026-11-18)

The Python dashboard has no user authentication. Keep it on loopback; never expose it as a public proxy for a Paperclip board key. Keep `dashboard/.env`, instance data, and agent output private. A remote Paperclip API should use HTTPS and scoped credentials.

### Local team operations

- Treat a board credential, task descriptions and terminal output as private. Use a trusted OS account, trusted checkout and trusted `herdr` executable on PATH. A local operator can start real work in an existing agent session. This is not a sandbox for untrusted issue authors or agent tools.
- The desk only accepts mutation requests with a loopback peer and Host (and same-origin browser context). Enrollment also requires loopback Paperclip on a shared filesystem. Do not forward an external proxy with a rewritten loopback Host to this service. Binding to `0.0.0.0` still exposes read-only company information without a login; keep the loopback default.
- Enrollment uses the board's normal **hire/approval** route. Browser input cannot select commands, executable paths, adapter environment or arbitrary pane keystrokes. Work stays in `backlog` until released; releasing a connected/native task can trigger a run immediately.
- Desk-created process workers use the run's credentials, not the dashboard's `.env`. The Herdr child receives no `PAPERCLIP_*` variables. A detected session gets one run at a time per enrolled worker; do not share the same interactive terminal between workers, companies, or the legacy Bash bridge. Manual members never send input. Check project/worktree and prompt content before release.
- Human-review confirmation is requested in Paperclip, not inferred from terminal text. If delivery or bookkeeping is ambiguous, inspect the issue and terminal before any re-execution. The older optional `bridge.sh` has different semantics, including publishing terminal output in comments; it is **not** the worker enrolled by the desk.

The project-local npm install pins the official stable `paperclipai@2026.1106.0`. Two scoped patch overrides replace the upstream `better-auth` 1.7.2 and `@vercel/cli-config` 0.3.0 (including its old Zod) without downgrading the CLI. Global/npm-cache installations do **not** use this lockfile. Revisit the overrides when updating Paperclip.

At review time `npm audit --omit=dev` on the lockfile still reported **1 high, 4 moderate, 0 critical** entries (counts include dependents). The remaining advisories are for [Zod bundled inside the upstream server](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5) and [uuid via svix](https://github.com/advisories/GHSA-w5hq-g745-h8pq). An audit finding is not proof of exploitability in this setup, but this is not a production security clearance. Track a stable upstream update; do not run `npm audit fix --force` to roll back the runtime or edit vendored files in `node_modules`.
