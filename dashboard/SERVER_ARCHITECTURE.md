# Server Architecture Overview

## Frontend Stack
- Single HTML file with embedded CSS and JS
- No build step required
- Uses vanilla JavaScript (no frameworks)
- Polls backend every 5 seconds

## Backend Stack
- Python 3.10+, **no third-party dependencies**
- `http.server` (stdlib) — the HTTP server behind `DashboardHandler`
- `urllib.request` (stdlib) — HTTP client for the Paperclip API
- `subprocess` — invokes the Herdr CLI

Flask and urllib3 are **not** used anywhere in this project.

## File Layout

```
dashboard/
├── app.py                 # Backend HTTP server
├── index.html             # Frontend UI
├── test_apis.py           # API tests
├── .env.example           # Configuration template
├── .gitignore             # Git exclusions
├── README.md              # Quick start guide
├── CONSTRUCTION.md        # Detailed construction guide
└── .env                   # Actual config (gitignored, read at startup)
```

`app.py` reads `dashboard/.env` at import time through `load_env_file()`, so values
from that file apply without exporting them in the shell. Real environment
variables are used when the file does not specify that key.

## API Endpoints

### GET /api/agents
- Returns: `{"agents": [...], "paperclip_online": bool}`
- Use: Fetch all agents from Paperclip

### POST /api/agents/<id>/heartbeat/invoke
- Body: (empty)
- Returns: `{"agent_id": "...", "status": "triggered", "response": {...}}`
- Use: Wake up an agent

### GET /api/tickets
- Query params: `assigneeAgentId=...&status=...`
- Returns: `{"tickets": [...], "paperclip_online": bool}`
- Use: List tickets with filters

### GET /api/agents/<id>/output
- Query params: `lines=120&source=recent-unwrapped`
- Returns: `{"agent_id": "...", "herdr_agent_name": "...", "output": "...", "success": bool, ...}`
- Use: Fetch agent output from Herdr
- Target resolution (`derive_herdr_agent_name`): explicit `HERDR_AGENT_MAP` entry (by Paperclip id, then by agent name) → live `herdr agent list` name match (trailing role words such as `-Worker`/`-Coder` are ignored) → the id itself when Herdr already uses it as an agent name or pane id.
- When nothing resolves, `success` is `false`, `herdr_agent_name` is `null` and `error` explains which `HERDR_AGENT_MAP` entry to add and lists the live Herdr targets. `herdr agent read` is never called with a Paperclip UUID.

### GET /health
- Returns: `{"status": "ok", "paperclip": bool}`
- Use: dashboard liveness plus Paperclip readiness (`GET /api/health`, not a company or agent lookup)

## HTTP Request Flow

### 1. Initial Load
```
User opens http://localhost:8000
        ↓
Frontend loads index.html
        ↓
Frontend polls GET /api/agents (5s interval)
        ↓
Backend calls Paperclip API
        ↓
Frontend displays agent cards
```

### 2. Wake Up Agent
```
User clicks "Wake Up" button
        ↓
Frontend sends POST /api/agents/<id>/heartbeat/invoke
        ↓
Backend calls Paperclip heartbeat endpoint
        ↓
Paperclip triggers agent (via bridge.sh/hermes_local)
        ↓
Frontend polls /api/agents/<id>/output (after 1.5s)
        ↓
Backend calls herdr agent read
        ↓
Frontend displays output in card
```

### 3. Manual Prompt (Placeholder)
```
User types in textarea and clicks "Send"
        ↓
Frontend sends POST /api/agents/<id>/prompt
        ↓
Backend returns "not_implemented_yet"
        ↓
Frontend alerts user
```

## Configuration Flow

`dashboard/.env` (UTF-8, optional BOM) overrides shell variables; absent keys
fall back to the environment, then code defaults. The Windows launcher persists
explicit command-line settings without replacing unrelated keys. See
[the dashboard README](README.md) for the configuration table.

An explicit company id is checked using its company endpoint (also works for
scoped credentials). Without one, exactly one company must be discoverable via
`GET /api/companies`. A healthy empty instance is not an offline instance.
`PAPERCLIP_API_KEY`, if set, is used only on server-side Paperclip API requests;
public readiness probes do not require it.

## State Management Strategy

### Frontend (Client-side)
- **State**: `agents` array, `tickets` array
- **Persistence**: localStorage (survives refresh)
- **Polling**: setInterval (5s)
- **Caching**: LocalStorage updates every poll
- **Error Handling**: Show error message, continue polling

### Backend (Server-side)
- **State**: None (all state comes from external services)
- **Caching**: Brief agent-name mapping caches; collection endpoints read fresh data
- **Concurrency**: a single-threaded `HTTPServer` — one request at a time
- **Error Handling**: Use 409 for missing/ambiguous company settings, 401/403 for upstream access failures, 503 for an unreachable server

## Scaling Considerations

### Current (Single Process)
- One `http.server.HTTPServer` process
- Runs on one host/port
- No database of its own
- Polls external services

### Potential Improvements
- Switch to `http.server.ThreadingHTTPServer` for concurrent requests
- Put the dashboard behind a reverse proxy and keep it bound to loopback
- Add Redis for session storage
- Implement rate limiting
- Add authentication middleware
