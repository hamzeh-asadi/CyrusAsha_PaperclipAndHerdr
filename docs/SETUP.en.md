# Setting up the Paperclip × Herdr team desk

[Back to the bilingual overview](../README.md) · [راهنمای فارسی](SETUP.fa.md)

## 1. Start the local services

From the root (the directory containing `package.json`), use Node **24.15.0 or newer in the 24.x line, or 26+**, npm **11.16+** and Python **3.10+**. The npm dependency is the official `paperclipai`, not the similarly named `paperclip` package. Python uses the standard library. You do **not** need Git Bash, jq, Herdr, an LLM key, Hermes or MCP just to open the planner or create manual assignments.

**Windows:** double-click `setup-dashboard.cmd` or run `.\setup-dashboard.cmd` in PowerShell. The launcher finds a working interpreter directly (PyManager is not required). It checks Paperclip readiness, reuses a running server and only bootstraps a missing server for the default local URL. Allow time and disk space for the first `npm ci` and embedded PostgreSQL setup. The readiness timeout starts **after installation**. To select a specific interpreter or a nondefault running instance:

```powershell
.\setup-dashboard.cmd -PythonVersion 3.14
# OR supply the real path to your chosen interpreter:
.\setup-dashboard.cmd -PythonExe "D:\Tools\Python315\python.exe"
# OR connect to a server you already run on another port:
.\setup-dashboard.cmd -PaperclipUrl http://localhost:3200 -DashboardPort 8080
```

**Two-terminal alternative (Windows/macOS/Linux):** run `npm ci` followed by `npm start` in one terminal and keep it open. In the other, run `python dashboard/app.py --open-browser` (`python3` if appropriate). In PowerShell, use `npm.cmd` if policy blocks `npm.ps1`.

Paperclip normally listens at `http://localhost:3100`; check its printed URL and `/api/health` (`status: "ok"`). The desk normally listens at `http://localhost:8000`. Do not start a second server for the same instance. For a custom data directory, use the same OS user and directory every time, e.g. `npm start -- --data-dir "D:/AI-Workspace/paperclip-data"`. Do not delete existing data to fix a startup failure. Optional Copilot assets are **not** needed for this desk; `npm run setup:copilot` is an opt-in step for that adapter on supported platforms.

## 2. Pick the company, then register the team

For a linked member, install **[Herdr](https://github.com/herdrdev/herdr)** using its platform instructions (not `npm install herdr`). Start `herdr` from the directory the agent should edit. For a manual member you can skip this installation entirely. Use the official [Antigravity](https://antigravity.google) or [Freebuff](https://freebuff.com) installer as appropriate, and open the agent once to complete sign-in.

Create a company in Paperclip if necessary. A healthy server with an empty roster is normal. The desk selects a sole company automatically. If there are several, set `PAPERCLIP_COMPANY_ID` to the intended ID from `/api/companies` or use the launcher's `-CompanyId`. Confirm the company name in the desk header before writing anything.

- **Manual (Freebuff or another tool):** choose the preset or enter a name in **Agent team**, select **Manual**, and register. This creates a real company member for assignment. Open the agent application yourself; starting work later will give you text to copy. No automated input goes to a shell or an unrecognized TUI.
- **Linked (e.g. Antigravity CLI):** install the agent and sign in according to its vendor's instructions. Start Herdr in the project directory, then run the agent (e.g. `agy`) **inside a Herdr pane**, not a nested copy of Herdr. Check `herdr agent list` from the same OS user/session. Select the detected session in the desk and register. Prefer a stable name; an unnamed agent is pinned to its terminal identity, not just a recyclable pane number. An empty target list is not an empty Paperclip roster.
- **Already in Paperclip:** existing eligible members can own subtasks without re-enrollment. Their native adapters are not overwritten. Hermes is optional; if used, configure its supported Paperclip adapter and model separately. You don't need a manager agent to split work in this desk.
- **Approvals:** the desk uses Paperclip's normal hire route. Review pending hires in the company's **Approvals**; wait for provisioning to finish. Only ready members can be selected as owners. A name or target collision does not silently repurpose another member.

The registered local `process` adapter stores the Python and worker paths. Keep the checkout and interpreter accessible to Paperclip. Docker, WSL and native Windows do not necessarily share these paths or a Herdr session. Use separate terminals/worktrees when independent agents edit the same repository. The desk does not create worktrees or merge branches.

## 3. Plan, release, verify

1. In **Task planner**, choose a new or existing parent and enter up to 20 assigned steps. Each child is a Paperclip issue with its own assignee and parent. The three-step template is just editable text. The order of rows does not create scheduling dependencies.
2. Saving writes **backlog** issues; it does not dispatch. If a response is lost, retry the same request from the still-open page. The same per-row keys prevent duplicates. The browser stores **only the language preference**; a reload loses the pending request and draft. Check the board before recreating anything.
3. In **Company work**, release only a ready item. A connected member moves from backlog to todo, which may trigger a run immediately (no second wake needed). A manual member moves to in-progress. Copy its sheet into the actual agent app, not a shell prompt.
4. Linked delivery checks the run, assignee, checkout and ready Herdr target. A verified idle/done return leads to **human review**, not automatic completion. For manual work, use **Ready for review** after checking the result. Open the issue in Paperclip to resolve the review. If a target blocks, disappears, times out (30 minutes) or only the final bookkeeping fails, inspect the run and terminal before sending any work again.

The **فارسی / English** control changes the desk immediately. It does not translate saved issues, rename agents, change Paperclip's own UI language, issue a wake or discard the current plan.

## 4. Settings and diagnostics

`dashboard/.env` overrides the corresponding shell environment keys; the file is optional for defaults. Copy [the example](../dashboard/.env.example) if needed. Restart **the dashboard** after changing it. Windows launcher reruns preserve unrelated settings.

| Setting | Purpose |
|---|---|
| `PAPERCLIP_API_URL` | Base URL, no `/api` suffix. Default `http://localhost:3100`. |
| `PAPERCLIP_COMPANY_ID` | Explicit company ID if automatic single-company selection is unsuitable. |
| `PAPERCLIP_API_KEY` | Only for authenticated access: scoped credential authorized for the intended operation. Server-side only. |
| `DASHBOARD_HOST` / `DASHBOARD_PORT` | Default `127.0.0.1:8000`. No user login; do not expose publicly. |
| `HERDR_AGENT_MAP` | Optional **read-output** mapping for legacy members with different names. It neither registers agents nor routes work. |

Use `python dashboard/test_connectivity.py` for a read-only check and `npm run doctor` for Paperclip (pass the same `--data-dir` as at startup). On Windows:

```powershell
curl.exe --noproxy "*" --max-time 8 http://127.0.0.1:3100/api/health
Get-NetTCPConnection -State Listen -LocalPort 3100 -ErrorAction SilentlyContinue
```

If Python was selected successfully but `/api/health` times out, check Paperclip's terminal, port and process; `-StartupTimeout 300` is available for a slow cold start. If `localhost` fails and `127.0.0.1` works, use `-PaperclipUrl http://127.0.0.1:3100`. For a missing native module or `EBADENGINE`, check Node/npm versions, platform (Windows embedded PostgreSQL: x64), disk space and the **first npm error**. Do not disable required install scripts or remove optional platform dependencies.

## 5. Legacy Bash bridge (not required)

Previously configured members may use [`bridge.sh`](../bridge.sh) with Bash, curl, jq and Herdr. This is **not** the Python worker enrolled by the desk. Its adapter environment accepts `HERDR_TARGET`, `HERDR_MODE` (`agent` or experimental `pane`), `WAIT_MS` (default 1800000), `QUIET_SEC` (45) and `DONE_STATUS` (`in_review`). It can publish terminal output in issue comments. Screen quietness in pane mode is not proof of completion. The pinned Paperclip may reject a bare transition to review with HTTP 422 if no valid reviewer path exists. Inspect the work; do not redispatch a completed task to repair its status. Never point two workers or bridges at the same interactive terminal.

See [the architecture](../dashboard/SERVER_ARCHITECTURE.md), [test instructions](../dashboard/CONSTRUCTION.md), [security notes](../SECURITY.md) and [verification limits](../PROJECT_STATUS.md). A simulated CLI in an integration test does not validate a real coding-agent session on your machine.
