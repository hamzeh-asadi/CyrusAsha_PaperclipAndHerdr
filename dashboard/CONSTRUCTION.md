# Working on the local team desk

See the [Persian desk guide](README.md) or [English setup guide](../docs/SETUP.en.md) and [SERVER_ARCHITECTURE.md](SERVER_ARCHITECTURE.md) for the API and state transitions. From the repository root:

```sh
python -m unittest discover -s dashboard -v   # independent mock boards / run identities
node --check dashboard/i18n.js                # no JS build or install needed
node --check dashboard/desk.js
python tests/test_bridge.py                  # separate, legacy Bash bridge fixtures
python dashboard/test_connectivity.py        # read-only check of your configured Paperclip
```

When changing behavior, add tests at the relevant boundary:

- `test_apis.py`: live loopback HTTP fixtures for readiness, company resolution, credentials and launcher compatibility.
- `test_locale.py`: catalog coverage, matching arguments across languages, local asset routes and the HTTP error contract in both languages.
- `test_team_desk.py`: desk HTTP ACLs, approval-preserving hires, plan validation, partial creation/replay and manual handoff.
- `test_herdr_worker.py`: run identity and issue scope, checkout conflicts, target identity, CLI failure and human-review bookkeeping. Do not inject a dashboard board key to make a worker test pass.

## Bilingual browser check & README images

`tests/ui/desk.cjs` opens the actual frontend against a temporary loopback fixture with sample companies/issues. It does not read `.env`, start Paperclip/Herdr or contact real agents. It checks FA/EN direction and persistence, all three views on mobile, an edited draft, retained assignee/filter and an identical plan retry across a language change. Without `--screenshots` it writes no images. Browser tools are **optional development tools**, not dashboard dependencies.

With Node 24, an installed Chromium/Chrome/Edge, and `puppeteer-core@24.43.1` in a disposable directory, for example in PowerShell:

```powershell
$tools = Join-Path $env:TEMP 'cyrusasha-desk-ui'
npm.cmd install --prefix $tools --ignore-scripts --no-audit --no-fund puppeteer-core@24.43.1
$env:NODE_PATH = Join-Path $tools 'node_modules'
$env:CHROME_BIN = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' # or actual Chrome path
node tests/ui/desk.cjs
node tests/ui/desk.cjs --screenshots    # refreshes only the six README captures
```

On Linux/macOS set `NODE_PATH` and `CHROME_BIN` to the corresponding local paths. Screenshots are taken after fonts load, with a separately selected sample dataset for each capture; changing the real UI language never translates issue titles. Add labels to `strings.json` in **both** languages, using the same `{placeholders}`. The default UI language is Persian; diagnostics without an explicit `Accept-Language` use English. Do not replace translated text with HTML.

## Optional full-stack acceptance check

Use a **disposable local Paperclip instance and a test company**. Enrollment, release and review write real records. Do not point a smoke test at an operator's board or coding-agent terminal. A simulated `herdr` on a test PATH can return the real JSON shapes (`result.agents`, `result.agent` with `terminal_id`, `agent`, readiness and status); label that as a simulated CLI, not a real coding-agent run.

1. Open the desk locally in either language. Register a manual member and a detected test session. Repeat one registration: the same member must be returned. Enable hire approval on the test company to check that a pending hire is visible but cannot be assigned until approved and active.
2. Create two assigned steps. Confirm `backlog`, the same `parentId`, distinct assignees and **zero** runs until release. Repeat the exact plan request: same parent and child IDs. Try splitting an existing open ticket too.
3. Release one manual step, copy the sheet, then request review. Verify a pending human confirmation in Paperclip, no terminal input and no automatic run.
4. Release the connected step. Verify the prompt at the selected target only; check the actual run, issue status and pending interaction. A missing/busy/blocked/replaced terminal or failed checkout must not produce a successful review. Never treat idle as proof the implementation is correct.
5. Open a task and pending hire from the dashboard on the actual board; check both RTL and LTR at a narrow viewport and keyboard access to form fields. Verify the page remains understandable when Paperclip or Herdr is unavailable.

Keep instance data, keys, run logs, personal screenshots, browser tooling and drafts out of the repository. Only the explicitly generated sample images belong in `docs/screenshots/`. The optional font in `fonts/` is the Arabic subset of Vazirmatn, redistributed with its SIL OFL license; it does not require network access at runtime.
