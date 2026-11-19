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

<a id="postgres-reuse"></a>

### “Refusing to reuse PostgreSQL: its data directory belongs to another instance” (Windows)

This is Paperclip stopping **before the desk starts**. After finding a live PID in the embedded cluster's `postmaster.pid`, Paperclip asks PostgreSQL which directory it serves. In the pinned version **both** a failed SQL lookup and a nonmatching path produce this message. A passing directory check in `doctor` does not prove the connection works. The launcher's exit code is a consequence, not the cause.

**If your original board is already open**, check the API URL printed by that server (not the database port):

```powershell
$board = 'http://127.0.0.1:3100' # replace with the original board's actual base URL
(Invoke-RestMethod "$board/api/health" -TimeoutSec 5).status
```

If it returns `ok` **and you recognize your existing company/tickets in that board**, connect the desk without bootstrapping even if the connection drops:

```powershell
.\setup-dashboard.cmd -ExistingOnly -PaperclipUrl "$board"
```

**Otherwise, diagnose the existing instance first.** In the checkout, under the same Windows account and environment used to launch Paperclip:

```powershell
$cfg = Read-Host 'Paste the path after Config: in the failed start (without quotes)'
.\setup-dashboard.cmd -DiagnosePostgres -ConfigPath "$cfg"
```

Without `-ConfigPath` the check uses `PAPERCLIP_CONFIG`, the nearest `.paperclip/config.json`, or the current Paperclip home/instance. Compare the path printed locally. `-ConfigPath` is **only** for this diagnostic; Paperclip's own `--data-dir` selects its **home**, not a PostgreSQL `db` folder. The check inspects the declared embedded config, not `.env` overrides. It installs nothing, starts/stops no service, runs no repair and changes no config, data or lock file. Only after verifying the PID, Windows listener owner and lock directory does it run one read-only SQL query on `127.0.0.1` using the **port in the lock** (which may differ from the configured DB port).

| `DB-CHECK` result | Meaning and next step |
|---|---|
| `server-dir-matches` | The server returned the expected path **now**. Check the original Paperclip console/API and company; this is not permission to start a second server. |
| `same-dir-different-spelling` / `dir-identity-unverified` | The paths differ after Node normalization. In the first case filesystem IDs match; in the second the identity is unknown. Check the original path spelling, drive or junction. Do not bypass the upstream guard or rename the directory. |
| `server-dir-differs` / `pid-file-dir-differs` / `listener-owner-differs` / `pid-not-postgres` | Conflicting directory, lock or process evidence. The PID might even have been recycled. Leave it alone. Identify the original instance, owner and launch command before any restart. |
| `sql-auth-failed` | Login or reading the setting was denied. Inspect that instance's local PostgreSQL log/access settings; do not reset a role or change authentication to get past the check. |
| `sql-not-ready` / `sql-timeout` / `sql-unavailable` | The lookup did not complete. If the original service is starting, let it finish and repeat **the check**, not setup. A different directory has not been established. |
| Missing/unreadable config or lock, missing PID/listener, `*-unverified` or `probe-unavailable` | No conclusion about ownership. Confirm the `Config:` path, same account and original launch environment. For the SQL probe, `node.exe` and the project's already-installed `postgres` dependency must be available. |

Do not delete `postmaster.pid`, kill a PID, create a fresh home, or point this installation at a different database as a workaround. If a restart is necessary, stop **only your identified original instance** normally through its own console/service manager. Before any database repair, verify the instance and its backup. For support share **only** `DB-CHECK: …`, whether `/api/health` returned `ok`, and whether the printed config matched the original. Do not post `.env`, a connection string, full config/logs or private paths.

## 2. Pick the company, then register the team

For a linked member, install **[Herdr](https://github.com/herdrdev/herdr)** using its platform instructions (not `npm install herdr`). Start `herdr` from the directory the agent should edit. For a manual member you can skip this installation entirely. Use the official [Antigravity](https://antigravity.google) or [Freebuff](https://freebuff.com) installer as appropriate, and open the agent once to complete sign-in.

Create a company in Paperclip if necessary. A healthy server with an empty roster is normal. The desk selects a sole company automatically. If there are several, set `PAPERCLIP_COMPANY_ID` to the intended ID from `/api/companies` or use the launcher's `-CompanyId`. Confirm the company name in the desk header before writing anything.

- **Manual (Freebuff or another tool):** choose the preset or enter a name in **Agent team**, select **Manual**, and register. This creates a real company member for assignment. Open the agent application yourself; starting work later will give you text to copy. No automated input goes to a shell or an unrecognized TUI.
- **Linked (e.g. Antigravity CLI):** install the agent and sign in according to its vendor's instructions. Start Herdr in the project directory, then run the agent (e.g. `agy`) **inside a Herdr pane**, not a nested copy of Herdr. In the desk select **the running Herdr server session**, then **the detected agent inside it**, and register. See the [Windows checks](#desk-diagnostics) if either list is empty. Prefer a stable name; an unnamed agent is pinned to its terminal identity, not just a recyclable pane number. An empty target list is not an empty Paperclip roster.
- **Already in Paperclip:** existing eligible members can own subtasks without re-enrollment. Their native adapters are not overwritten. Hermes is optional; if used, configure its supported Paperclip adapter and model separately. You don't need a manager agent to split work in this desk.
- **Approvals:** the desk uses Paperclip's normal hire route. Review pending hires in the company's **Approvals**; wait for provisioning to finish. Only ready members can be selected as owners. A name or target collision does not silently repurpose another member.

A new linked `process` adapter stores the selected server name, Herdr executable, and the Python and worker paths. Existing unscoped workers are not silently rebound. Keep the checkout and interpreter accessible to Paperclip. Docker, WSL and native Windows do not necessarily share these paths or a Herdr session. Use separate terminals/worktrees when independent agents edit the same repository. The desk does not create worktrees or merge branches.

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
| `HERDR_DESK_EXE` | Optional absolute path to the trusted `herdr.exe` (or `herdr`); use a stable install path. No arguments or `%VARIABLE%` expansion. Otherwise uses PATH, then the standard Windows compatibility alias. |
| `HERDR_AGENT_MAP` | Optional **read-output** mapping for legacy members with different names. It neither registers agents nor routes work. |

Use `python dashboard/test_connectivity.py` for a read-only check and `npm run doctor` for Paperclip (pass the same `--data-dir` as at startup). On Windows:

```powershell
curl.exe --noproxy "*" --max-time 8 http://127.0.0.1:3100/api/health
Get-NetTCPConnection -State Listen -LocalPort 3100 -ErrorAction SilentlyContinue
```

If Python was selected successfully but `/api/health` times out, check Paperclip's terminal, port and process; `-StartupTimeout 300` is available for a slow cold start. If `localhost` fails and `127.0.0.1` works, use `-PaperclipUrl http://127.0.0.1:3100`. For a missing native module or `EBADENGINE`, check Node/npm versions, platform (Windows embedded PostgreSQL: x64), disk space and the **first npm error**. Do not disable required install scripts or remove optional platform dependencies.

<a id="desk-diagnostics"></a>

### Windows: separate the server, pane and agent

From a fresh **ordinary PowerShell** on the same Windows account and installation as the desk:

```powershell
Get-Command herdr.exe -ErrorAction SilentlyContinue
herdr --version
(herdr session list --json | ConvertFrom-Json).sessions | Select-Object name,running
```

- **Command not found:** install the [official native Herdr release](https://github.com/herdrdev/herdr/releases), open a new terminal and restart the desk. If it works in your shell but not the desk, set `HERDR_DESK_EXE` in `dashboard/.env` to the full path of the installed CLI. Keep the adjacent runtime files. The installer’s stable alias is normally `%LOCALAPPDATA%\Programs\Herdr\bin\herdr.exe`.
- **No running session:** in the project directory in another terminal, start `herdr` (or `herdr --session studio` for a named session). Inside one of **its panes** start `agy`, sign in and wait for the agent prompt. Do not start a second Herdr inside the first, or type a work sheet into PowerShell.
- **Server running, agent missing:** in the *outside* terminal run the following. Replace `studio` with the actual running name (`default` is a name too):

```powershell
herdr --session studio pane list
herdr --session studio agent list
```

`pane list` shows terminals; only `result.agents` in `agent list` contains detected agents. There is no `--json` flag on `agent list`. An ordinary shell or a separate desktop window is not a candidate. Rescan, choose that server and that agent. If there is still no detected target, **Manual** works without Herdr. The desk enumerates local default/named servers, not arbitrary remote/custom sockets. Use the same account, elevation and Herdr configuration root for Paperclip, the desk and Herdr; Windows and WSL are separate. For a protocol mismatch, compare `herdr --version` with `herdr --session studio status`; save open work before restarting/upgrading a server (stopping it closes panes).

### Hermes-CEO: verification is not a run

On the **saved member's** card choose **Configuration & agent test** (Paperclip: **Harness / Runtime → Run test → Test details**). Check the actual adapter type, not the name “CEO”. Fix the first **error**, or the first **warning** if there is no error, save changes and test again. Then use **Retry now** if verification is still pending. It retries provisioning, not an issue. A member that has not reached `ready` cannot be woken or assigned by the desk. The desk never runs this test automatically; a managed test can contact a model provider.

| Adapter / check in pinned Paperclip | What to check |
|---|---|
| `hermes_local` · CLI not found / version failed | Use the [official Hermes installer](https://github.com/NousResearch/hermes-agent#installation). In the environment that **starts Paperclip**, check `Get-Command hermes -All` and `hermes --version`. The adapter directly executes the CLI: a PowerShell alias, a `.cmd` wrapper alone, a Desktop shortcut, or Hermes in another WSL distro does not prove `hermes.exe` is available. If using a custom command, point it at the real CLI executable. |
| `hermes_python_missing` / `hermes_python_old` | The unmanaged local adapter checks **`python3 --version`** (3.10+), not `py` or the `python.exe` selected by the desk launcher. Ensure a working `python3` is available on Paperclip’s PATH. After a PATH change, safely restart the **Paperclip process** from a new terminal using its existing instance, once active work is safe. |
| `hermes_no_api_keys`, provider mismatch, `hermes_hello_probe_failed` | For local credentials use `hermes setup` for the intended provider/model. For a managed AI connection check the saved agent's selected connection, endpoint and model. The managed probe tests that connection, not a separate interactive login. In this Paperclip version even an overall **warn** without a successful verification probe can hold the member in verification. |
| `hermes_gateway` · missing URL/key or health failure | This adapter talks to a Hermes **API server**, not to a local CLI or Herdr pane. Verify the API base URL, matching credential and reachability from Paperclip; use HTTPS for non-loopback gateways. A gateway credential is not a Paperclip board key. |

### An issue title looks like `?????`

`CYR-2` is an issue identifier; the text after it is the company's saved title. The desk flags standalone runs of literal ASCII `?` and the Unicode replacement character in the **decoded API response**, without changing the title. Open **the same issue** in Paperclip. If those characters are in the record and were not intended, re-enter the original title there. No font, language switch or automatic guess restores missing letters. If Paperclip shows the correct Persian, **do not rename it**: compare the current desk API and browser display. On a default local desk this read-only check prints just the ID and marker for an open issue:

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/api/tickets).tickets | Where-Object identifier -eq 'CYR-2' | Select-Object identifier,titleWarning
```

`literal_question_marks` / `replacement_character` describes the text, not the cause. No row? Check the active company and open the issue directly on the board (the desk lists open work). When reporting a problem, share only the marker, the first failing Hermes check (message/code with private details removed), Herdr version, and whether a server and agent were listed. Do not share `.env`, keys, full test responses or pane output.

## 5. Legacy Bash bridge (not required)

Previously configured members may use [`bridge.sh`](../bridge.sh) with Bash, curl, jq and Herdr. This is **not** the Python worker enrolled by the desk. Its adapter environment accepts `HERDR_TARGET`, `HERDR_MODE` (`agent` or experimental `pane`), `WAIT_MS` (default 1800000), `QUIET_SEC` (45) and `DONE_STATUS` (`in_review`). It can publish terminal output in issue comments. Screen quietness in pane mode is not proof of completion. The pinned Paperclip may reject a bare transition to review with HTTP 422 if no valid reviewer path exists. Inspect the work; do not redispatch a completed task to repair its status. Never point two workers or bridges at the same interactive terminal.

See [the architecture](../dashboard/SERVER_ARCHITECTURE.md), [test instructions](../dashboard/CONSTRUCTION.md), [security notes](../SECURITY.md) and [verification limits](../PROJECT_STATUS.md). A simulated CLI in an integration test does not validate a real coding-agent session on your machine.
