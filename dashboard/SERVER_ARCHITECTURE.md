# Team desk architecture

Paperclip owns company membership, approvals, assignments, issue hierarchy, run checkout and review. The dashboard is a local client, **not** another scheduler or database. The Herdr program and agent TUI run independently; their workspace is where the work actually happens.

| Component | Responsibility |
|---|---|
| `app.py` | stdlib HTTP server; `dashboard/.env`, health, company selection, local-operator checks, fixed static routes and read-only legacy output mappings |
| `team_desk.py` | Whitelisted roster/issue summaries, validated hires, plan creation and explicit status changes through an injected Paperclip client |
| `paperclip_client.py` | Stateless JSON transport. Caller supplies credentials. No bearer on health, no redirects, no system proxy for loopback. Shared human-review interaction protocol. |
| `herdr_worker.py` | Fixed `process` adapter entry point and detected-agent CLI helpers. Imports **no dashboard configuration**. No third-party Python packages. |
| `index.html`, `desk.js`, `desk.css`, `fonts/` | Persian RTL planner/team/work pages with same-origin requests and visible-page polling (5 s). Text rendering, local OFL font; no bundler, CDN, or browser storage. |

## Dashboard HTTP contract

All paths are relative to the dashboard, not Paperclip. `/health` is service readiness, not a count of accessible companies. Actor-visible company data is fetched afresh; a sole company can be inferred, otherwise configure `PAPERCLIP_COMPANY_ID`. An unknown configured ID, no company or ambiguous selection is a conflict, not a fabricated empty roster.

| Method and path | Input / result |
|---|---|
| `GET /health` | `{status, paperclip}` from a public upstream health probe |
| `GET /api/agents` | `{company, agents, paperclip_online, localControl}`. Never returns adapter environment or credentials. Local navigation links open the actual Paperclip board. |
| `GET /api/tickets` | Optional `assigneeAgentId`, `status`; defaults to open statuses including backlog, review and blocked. Returns `tickets` with identifiers, title, description, parent and assignee IDs. |
| `GET /api/herdr/targets` | Local only. Returns detected `{target, kind, terminal, status, ...}` records from `herdr agent list`; a bare shell is not a candidate. |
| `GET /api/agents/<id>/output` | Local only. Checks company membership, binding, allowed source and 1–200 lines. Legacy read targets can be set with `HERDR_AGENT_MAP`. |
| `POST /api/team/enroll` | `companyId, name, mode` (`manual` or `agent`); Echo the selected `target, terminal, kind` for `agent`; revalidated against live discovery to catch pane replacement. Requires loopback Paperclip with the same filesystem/user. Returns `agent, existing` and, for new hires, `needsApproval`. |
| `POST /api/plans` | `companyId, requestId` (UUID), `parentId` or new `title`, `steps` of `{title, description?, assigneeAgentId}`. Returns `parent, children`. |
| `POST /api/work/advance` | `companyId, issueId, assigneeAgentId, action` (`release` or manual `review`). Rechecks the company, assignee and status. Returns `issue`. |
| `POST /api/agents/<id>/heartbeat/invoke` | Explicit user wake, company checked; not for a manual member. Ordinary plan/release flow needs no second wake. |

Desk POST bodies must be JSON objects, at most 128 KiB, with only the listed fields. All mutations require a loopback peer and Host, and same-origin browser requests; forwarded headers confer no privilege. Read-only network binding is not authentication. Keep the default `127.0.0.1`.

## Planning is separate from execution

- Enrollment calls upstream `POST /api/companies/{id}/agent-hires`; no policy changes, self-approval, or overwrites of existing agents. Adapter command, args, and working directory are generated server-side. Timer off, on-demand only for a linked member, at most one simultaneous run per new member.
- Validate **all** rows and company membership before writing. Each issue is created in `backlog`. Children reference the actual parent and inherit its project and visibility. There is no cross-issue transaction: retry the same request with the same per-row idempotency keys. On partial failure the response names the parent and how many child responses were confirmed. Reloading the page discards the in-memory request; inspect the board before starting again.
- Releasing a connected/native member's task promotes backlog to todo using the upstream status version. This can itself enqueue a run. A manual release instead moves to in-progress, with no automated dispatch.
- The linked worker checks the identity/scope of its actual run and ownership of its assigned issue; a manual unscoped wake may claim one ready assignment. It never reclaims an old in-progress task, sends to a bare pane, or retries an ambiguous CLI submission. It uses `agent prompt --wait` on the selected idle, ready agent (30 min limit). An unnamed detected target is pinned to its terminal ID. A successful return must be idle/done on the same terminal. No raw terminal output is posted to the issue.
- After a verified return (or the operator's manual review action), create a pending `request_confirmation` for `human_only`, with continuation `none`, then PATCH `in_review` with that `reviewInteractionId`. A comment alone is not a review path in the pinned API. No automatic `done`. If final bookkeeping fails, inspect the terminal and repair the review on the board; do **not** resend completed work.
