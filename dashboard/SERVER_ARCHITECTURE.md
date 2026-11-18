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
variables always take precedence over the file.

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
- Returns: `{"status": "ok", "paperclip_online": bool}`
- Use: Health check

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

### 1. Environment Variables (highest priority — `.env` never overrides them)
```
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000
PAPERCLIP_API_URL=http://localhost:3100
PAPERCLIP_COMPANY_ID=...
HERDR_HOST=localhost
HERDR_PORT=50800
HERDR_AGENT_MAP=<paperclip-id-or-name>=<herdr-name-or-pane>,...
```

### 2. `dashboard/.env` (loaded by `load_env_file()` at import time)
```
PAPERCLIP_API_URL=http://localhost:3100
PAPERCLIP_COMPANY_ID=...
HERDR_AGENT_MAP=856affb4-...=agy-worker,Freebuff-Coder=w2:p1
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000
```

The file is opened with `utf-8-sig`, so a BOM (as written by PowerShell's
`Set-Content -Encoding UTF8`) does not corrupt the first key. Blank lines and
`#` comments are skipped, surrounding quotes are stripped, and a key that is
already present in the real environment is left untouched.

### 3. Code Defaults (fallback)
```python
PAPERCLIP_API_URL = "http://localhost:3100"
COMPANY_ID = "856affb4-69f1-44cb-a690-e4c2e6b2769d"
HERDR_HOST = "localhost"
HERDR_PORT = 50800
```

## State Management Strategy

### Frontend (Client-side)
- **State**: `agents` array, `tickets` array
- **Persistence**: localStorage (survives refresh)
- **Polling**: setInterval (5s)
- **Caching**: LocalStorage updates every poll
- **Error Handling**: Show error message, continue polling

### Backend (Server-side)
- **State**: None (all state comes from external services)
- **Caching**: No in-memory cache (each request fetches fresh data)
- **Concurrency**: a single-threaded `HTTPServer` — one request at a time
- **Error Handling**: Return HTTP 500 with error message

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
