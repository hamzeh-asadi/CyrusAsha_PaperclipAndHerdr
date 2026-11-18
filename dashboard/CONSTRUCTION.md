# Unified Dashboard - Construction Guide

## Overview

This dashboard builds a unified control plane over Paperclip+Herdr, enabling:

1. **Discovery**: Automatically scan and identify all agents via Paperclip API
2. **Heartbeat-based wake-up**: Trigger agents via heartbeat
3. **Centralized control**: One UI to manage all agents and tickets
4. **Output tracking**: Display recent agent output from Herdr
5. **Polling**: Auto-refresh every 5 seconds for live status

## Components

### 1. Backend (`dashboard/app.py`)

**Purpose**: Serve APIs that connect Paperclip and Herdr.

**Key Functions**:
- `list_agents_from_paperclip()`: Fetches all agents from Paperclip API
- `trigger_heartbeat(agent_id)`: Calls Paperclip's heartbeat endpoint
- `get_agent_output_from_herdr(agent_id)`: Reads agent output via Herdr CLI
- `DashboardHandler`: HTTP handler for endpoints:
  - `GET /api/agents` - List all agents
  - `POST /api/agents/<id>/heartbeat/invoke` - Wake up an agent
  - `GET /api/tickets` - List tickets
  - `GET /api/agents/<id>/output` - Get agent output
  - `GET /health` - Check system health

**Configuration**:
- Reads Paperclip URL, optional company ID, optional API key and Herdr mapping from `dashboard/.env` or the environment
- Falls back gracefully if Paperclip/Herdr are offline

### 2. Frontend (`dashboard/index.html`)

**Purpose**: Single-page UI that consumes the backend APIs.

**Features**:
- Agent cards with:
  - Name, type, role
  - Online/offline status badge
  - Last heartbeat timestamp
  - "Wake Up" button (triggers heartbeat)
  - Manual prompt box (to send commands to agent)
  - Live output window
- Tickets tab showing:
  - All tickets with status badges
  - Ticket ID and title
- Auto-polling every 5 seconds
- LocalStorage for state persistence
- Persian RTL support

**UI Structure**:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header                                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Refresh Button | Status Badge (Online/Offline)                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Tabs: [Agents] [Tickets]                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Tab: Agents                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Agent Card 1                                                       │   │
│  │   Name, Type, Role                                                 │   │
│  │   Status, Last Heartbeat                                           │   │
│  │   [Wake Up] Button                                                  │   │
│  │   Manual Prompt Box + Send Button                                  │   │
│  │   Output Window (last 120 lines)                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Agent Card 2 (etc)                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Tab: Tickets                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Ticket Item 1: "Fix login bug"                                      │   │
│  │   [in_progress] [ID: 1234]                                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ...                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. Setup Script (`setup-dashboard.ps1`)

**Purpose**: Automated setup and launch.

**Checks**:
- Python version
- Node/npm compatibility if a local Paperclip must be started
- Paperclip readiness (`GET /api/health`)
- Herdr installation

**Actions**:
- Bootstraps the pinned CLI for an unavailable default local instance; does not launch a local process for a remote URL
- Creates `dashboard/.env` when missing and updates only explicitly passed keys
- Opens browser to dashboard URL
- Starts the Python backend

### 4. Documentation (`dashboard/README.md`)

**Purpose**: Quick reference for usage.

**Contents**:
- Features overview
- Structure explanation
- Prerequisites
- Installation steps
- Environment variable configuration
- Known limitations

## Data Flow

```
User opens dashboard
        │
        ▼
Frontend loads from index.html
        │
        ▼
Frontend polls /api/agents (every 5 sec)
        │
        ▼
Backend calls Paperclip API -> returns agent list
        │
        ▼
Frontend displays agents and status
        │
        ▼
User clicks "Wake Up" on an agent
        │
        ▼
Frontend sends POST to /api/agents/<id>/heartbeat/invoke
        │
        ▼
Backend calls Paperclip heartbeat endpoint
        │
        ▼
Paperclip triggers agent (via bridge.sh or hermes_local)
        │
        ▼
Frontend polls again after 1.5s and fetches agent output
        │
        ▼
Backend calls herdr agent read -> returns last 120 lines
        │
        ▼
Frontend displays output in agent card
```

## State Management

**Frontend**:
- `agents`: Array of agent objects (stored in localStorage)
- `tickets`: Array of ticket objects (stored in localStorage)
- Polling: Runs on `setInterval` (5s)
- Transient state: Heartbeat triggers, pending prompts

**Backend**:
- No persistent state (state is read-only from Paperclip/Herdr)
- Only in-memory during request handling
- Configuration via environment variables

## Known Limitations

1. **Output source**: Only Herdr CLI is currently used. Other agent types (Hermes, Freebuff) may not produce visible output.
2. **Manual prompts**: `sendManualPrompt()` is a placeholder; real implementation requires Herdr CLI command construction.
3. **Herdr agent name resolution**: `derive_herdr_agent_name()` reads the live `herdr agent list` and matches Paperclip agent names; agents whose Herdr name differs must be listed in `HERDR_AGENT_MAP` (`<paperclip-id or name>=<herdr name or pane>`).
4. **Error recovery**: Some failures (offline APIs) don't auto-retry in this version.
5. **No permissions control**: All API calls use default credentials (from environment/config).

## Extension Ideas

1. Add per-agent settings (custom heartbeat interval, output line count)
2. Integrate comment display: fetch recent comments from Paperclip for each agent
3. Add status history: chart of last N heartbeats for each agent
4. Implement full manual prompt routing (not just placeholder)
5. Add filters: show only agents of a specific adapter type
6. Add ticket detail view: click ticket to see description and comments
7. Export to CSV/JSON: dump current state for offline analysis

## Troubleshooting

**Dashboard won't start**:
- Check if port 8000 is already in use: `netstat -ano | findstr :8000`
- Check Python: `python --version`
- No Flask or pip packages are required.

**Paperclip not detected**:
- Verify readiness: `curl http://localhost:3100/api/health`; test access: `python dashboard/test_connectivity.py`
- Check environment variable `PAPERCLIP_API_URL`
- Verify company ID matches your Paperclip instance

**Herdr not reachable**:
- Check Herdr installation: `herdr --version`
- Verify Herdr user matches Paperclip user
- Check that `herdr agent list` works as the dashboard user

**Agent output empty**:
- Check Herdr agent name mapping (`derive_herdr_agent_name`)
- Verify Herdr is actually outputting text (try `herdr agent read <name>` manually)
- Ensure agent is actually working (check its terminal window)
