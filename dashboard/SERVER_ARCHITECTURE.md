# Team desk architecture

Paperclip owns company membership, approvals, assignments, issue hierarchy, run checkout and review. The dashboard is a local client, **not** another scheduler or database. The Herdr program and agent TUI run independently; their workspace is where the work actually happens.

| Component | Responsibility |
|---|---|
| `app.py` | stdlib HTTP server; `dashboard/.env`, health, company selection, local-operator checks, fixed static routes and read-only legacy output mappings |
| `team_desk.py` | Whitelisted roster/issue summaries, validated hires, plan creation and explicit status changes through an injected Paperclip client |
| `paperclip_client.py` | Stateless JSON transport. Caller supplies credentials. No bearer on health, no redirects, no system proxy for loopback. Shared human-review interaction protocol. |
| `herdr_worker.py` | Fixed `process` adapter entry point and detected-agent CLI helpers. Imports **no dashboard configuration**. No third-party Python packages. |
| `index.html`, `desk.js`, `desk.css`, `fonts/`, `brand/` | Bilingual FA/RTL and EN/LTR planner, team and work pages. Same-origin requests and visible-page polling (5 s). Text rendering, local artwork and OFL font; no bundler or CDN. |
| `strings.json`, `i18n.js`, `desk_text.py` | Shared first-party message catalog, parameter formatting, document language/direction and structured errors. Only `fa` or `en` is stored in browser preferences. Drafts, retry keys, API data and credentials are not persisted by the UI. |

## Dashboard HTTP contract

All paths are relative to the dashboard, not Paperclip. `/health` is service readiness, not a count of accessible companies. Actor-visible company data is fetched afresh; a sole company can be inferred, otherwise configure `PAPERCLIP_COMPANY_ID`. An unknown configured ID, no company or ambiguous selection is a conflict, not a fabricated empty roster.

| Method and path | Input / result |
|---|---|
| `GET /health` | `{status, paperclip}` from a public upstream health probe |
| `GET /api/agents` | `{company, agents, paperclip_online, localControl}`. Includes lifecycle state and, when applicable, a verification-failed flag; never returns raw lifecycle errors, adapter environment or credentials. Local navigation links open the actual Paperclip board. |
| `GET /api/tickets` | Optional `assigneeAgentId`, `status`; defaults to open statuses including backlog, review and blocked. Returns `tickets` with identifiers, title, description, parent and assignee IDs. An optional `titleWarning` flags literal question-mark words or U+FFFD in the received text; it does not replace the title. |
| `GET /api/herdr/sessions` | Local only. Reads `herdr session list --json` and returns `sessions` with `name, running, unreachable`; omits socket paths, directories and raw errors. |
| `GET /api/herdr/targets?session=NAME` | Local only. Returns detected `{target, kind, terminal, status, ...}` records from that server's `agent list`. No pane fallback. Omitting the selector retains the legacy implicit read. |
| `GET /api/agents/<id>/output` | Local only. Checks company membership, binding, allowed source and 1–200 lines. Legacy read targets can be set with `HERDR_AGENT_MAP`. |
| `POST /api/team/enroll` | `companyId, name, mode` (`manual` or `agent`); Echo the selected `session, target, terminal, kind` for `agent`; revalidated against live discovery to catch pane replacement. Requires loopback Paperclip with the same filesystem/user. Returns `agent, existing` and, for new hires, `needsApproval`. |
| `POST /api/plans` | `companyId, requestId` (UUID), `parentId` or new `title`, `steps` of `{title, description?, assigneeAgentId}`. Returns `parent, children`. |
| `POST /api/work/advance` | `companyId, issueId, assigneeAgentId, action` (`release` or manual `review`). Rechecks the company, assignee and status. Returns `issue`. |
| `POST /api/agents/<id>/heartbeat/invoke` | Explicit user wake, company and readiness checked; not for a manual member. Ordinary plan/release flow needs no second wake. |

Error responses retain the plain `error` field. Desk-owned errors can also include `i18n: {key, vars}` for re-rendering an existing message after a language change. Raw user content and terminal output are not localized.

Desk POST bodies must be JSON objects, at most 128 KiB, with only the listed fields. All mutations require a loopback peer and Host, and same-origin browser requests; forwarded headers confer no privilege. Read-only network binding is not authentication. Keep the default `127.0.0.1`.

Native `hermes_local`/`hermes_gateway` agents run outside this integration. The **Configuration & agent test** link opens the saved member’s `/agents/{id}/runtime` board route; the desk does not post test requests, read secret configuration, or change lifecycle state. A non-ready lifecycle, invalid reporting chain, or non-assignable execution status blocks assignment, release and wake. Older responses without `lifecycleState` still use status/chain checks.

## Planning is separate from execution

- Enrollment calls upstream `POST /api/companies/{id}/agent-hires`; no policy changes, self-approval, or overwrites of existing agents. The command, arguments, working directory and linked CLI path are generated server-side. New bindings pass an explicit validated `--session` to list/get/read/prompt (including `default`). Existing unscoped workers retain their original environment-based behavior. Timer off, on-demand only for a linked member, at most one simultaneous run per new member.
- Validate **all** rows and company membership before writing. Each issue is created in `backlog`. Children reference the actual parent and inherit its project and visibility. There is no cross-issue transaction: retry the same request with the same per-row idempotency keys. On partial failure the response names the parent and how many child responses were confirmed. Reloading the page discards the in-memory request; inspect the board before starting again.
- Releasing a connected/native member's task promotes backlog to todo using the upstream status version. This can itself enqueue a run. A manual release instead moves to in-progress, with no automated dispatch.
- The linked worker checks the identity/scope of its actual run and ownership of its assigned issue; a manual unscoped wake may claim one ready assignment. It never reclaims an old in-progress task, sends to a bare pane, or retries an ambiguous CLI submission. It uses `agent prompt --wait` on the selected idle, ready agent (30 min limit). An unnamed detected target is pinned to its terminal ID. A successful return must be idle/done on the same terminal. No raw terminal output is posted to the issue.
- After a verified return (or the operator's manual review action), create a pending `request_confirmation` for `human_only`, with continuation `none`, then PATCH `in_review` with that `reviewInteractionId`. A comment alone is not a review path in the pinned API. No automatic `done`. If final bookkeeping fails, inspect the terminal and repair the review on the board; do **not** resend completed work.
