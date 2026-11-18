#!/usr/bin/env python3
"""
Backend server for Paperclip+Herdr unified dashboard.
Scans agents, triggers heartbeats, lists tickets, and fetches recent agent output.
"""

import os
import sys
import json
import time
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Optional
import subprocess
import urllib.request

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env_file(path: str) -> None:
    """Load KEY=VALUE pairs from a .env file.

    Real environment variables always win; the file only fills the gaps.
    Reads with utf-8-sig so the BOM written by PowerShell's Set-Content -Encoding UTF8
    does not corrupt the first key.
    """
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8-sig") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


load_env_file(ENV_FILE)

# Configuration
PAPERCLIP_URL = os.getenv("PAPERCLIP_API_URL", "http://localhost:3100")
COMPANY_ID = os.getenv("PAPERCLIP_COMPANY_ID", "856affb4-69f1-44cb-a690-e4c2e6b2769d")
HERDR_HOST = os.getenv("HERDR_HOST", "localhost")
HERDR_PORT = int(os.getenv("HERDR_PORT", 50800))
AGENT_PING_TIMEOUT = int(os.getenv("AGENT_PING_TIMEOUT", 2000))

def check_paperclip_online() -> bool:
    """Return True when the Paperclip company endpoint answers with 200."""
    try:
        req = urllib.request.Request(f"{PAPERCLIP_URL}/api/companies/{COMPANY_ID}", method="GET")
        with urllib.request.urlopen(req, timeout=2) as res:
            return res.status == 200
    except Exception:
        return False


def list_agents_from_paperclip() -> Dict[str, Any]:
    """Fetch the agent list from the Paperclip API."""
    url = f"{PAPERCLIP_URL}/api/companies/{COMPANY_ID}/agents"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as res:
        data = json.loads(res.read().decode("utf-8"))
    return {"agents": data, "paperclip_online": check_paperclip_online()}


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler exposing dashboard APIs."""

    def log_message(self, format, *args):
        # Disable default logging
        pass

    def send_json(self, data: Any, status: int = 200):
        """Helper to send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def send_error_json(self, message: str, status: int = 500):
        """Helper to send JSON error."""
        self.send_json({"error": message}, status=status)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        # Scan all agents
        if parsed.path == "/api/agents":
            self.handle_agents(query)
        # Ping a specific agent via heartbeat
        elif parsed.path.startswith("/api/agents/") and parsed.path.endswith("/heartbeat/invoke"):
            agent_id = parsed.path[len("/api/agents/"):-len("/heartbeat/invoke")]
            self.handle_heartbeat(agent_id, query)
        # List tickets (optional filter by agent)
        elif parsed.path == "/api/tickets":
            self.handle_tickets(query)
        # Recent output for an agent
        elif parsed.path.startswith("/api/agents/") and parsed.path.endswith("/output"):
            agent_id = parsed.path[len("/api/agents/"):-len("/output")]
            self.handle_agent_output(agent_id, query)
        # Health check
        elif parsed.path == "/health":
            self.send_json({"status": "ok", "paperclip": self.check_paperclip_online()})
        # Index
        elif parsed.path == "/":
            self.send_html_index()
        else:
            self.send_error_json("Not found", status=404)

    def do_POST(self):
        parsed = urlparse(self.path)

        # Trigger heartbeat manually via POST (alternative to GET)
        if parsed.path.startswith("/api/agents/") and parsed.path.endswith("/heartbeat/invoke"):
            agent_id = parsed.path[len("/api/agents/"):-len("/heartbeat/invoke")]
            self.handle_heartbeat(agent_id, {})
        # Submit a manual prompt for an agent
        elif parsed.path.startswith("/api/agents/") and parsed.path.endswith("/prompt"):
            agent_id = parsed.path[len("/api/agents/"):-len("/prompt")]
            self.handle_agent_prompt(agent_id)
        else:
            self.send_error_json("Not found", status=404)

    def check_paperclip_online(self) -> bool:
        """Delegate to the module-level helper (kept as a method for existing callers)."""
        return check_paperclip_online()

    def handle_agents(self, query: Dict[str, list]) -> None:
        """List all agents from Paperclip."""
        try:
            agents = self.list_agents_from_paperclip()
            self.send_json(agents)
        except Exception as e:
            self.send_error_json(str(e), status=500)

    def list_agents_from_paperclip(self) -> Dict[str, Any]:
        """Delegate to the module-level helper (kept as a method for existing callers)."""
        return list_agents_from_paperclip()

    def handle_heartbeat(self, agent_id: str, query: Dict[str, list]) -> None:
        """Trigger a heartbeat for the specified agent."""
        try:
            result = self.trigger_heartbeat(agent_id)
            self.send_json(result)
        except Exception as e:
            self.send_error_json(str(e), status=500)

    def trigger_heartbeat(self, agent_id: str) -> Dict[str, Any]:
        """Call Paperclip's heartbeat endpoint for the agent."""
        import urllib.request
        url = f"{PAPERCLIP_URL}/api/agents/{agent_id}/heartbeat/invoke"
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as res:
            resp = json.loads(res.read().decode("utf-8"))
        return {"agent_id": agent_id, "status": "triggered", "response": resp}

    def handle_tickets(self, query: Dict[str, list]) -> None:
        """List tickets (optional filter by agent)."""
        try:
            tickets = self.list_tickets_from_paperclip(query)
            self.send_json(tickets)
        except Exception as e:
            self.send_error_json(str(e), status=500)

    def list_tickets_from_paperclip(self, query: Dict[str, list]) -> Dict[str, Any]:
        """Fetch tickets from Paperclip API."""
        import urllib.request
        assignee = query.get("assigneeAgentId", [None])[0] if query.get("assigneeAgentId") else None
        status = query.get("status", ["todo,in_progress"])[0] if query.get("status") else "todo,in_progress"
        url = f"{PAPERCLIP_URL}/api/companies/{COMPANY_ID}/issues?assigneeAgentId={assignee}&status={status}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
        return {"tickets": data, "paperclip_online": self.check_paperclip_online()}

    def handle_agent_output(self, agent_id: str, query: Dict[str, list]) -> None:
        """Get recent output for the specified agent from Herdr."""
        try:
            output = self.get_agent_output_from_herdr(agent_id, query)
            self.send_json(output)
        except Exception as e:
            self.send_error_json(str(e), status=500)

    def get_agent_output_from_herdr(self, agent_id: str, query: Dict[str, list]) -> Dict[str, Any]:
        """Read recent agent output via Herdr CLI."""
        lines = query.get("lines", ["120"])[0] if query.get("lines") else "120"
        source = query.get("source", ["recent-unwrapped"])[0] if query.get("source") else "recent-unwrapped"
        # Derive Herdr agent name from Paperclip agent_id if possible
        herdr_agent_name = self.derive_herdr_agent_name(agent_id)

        if herdr_agent_name:
            cmd = ["herdr", "agent", "read", herdr_agent_name, f"--source={source}", f"--lines={lines}"]
        else:
            # Fall back to looking up by pane via herdr agent get (then derive name)
            cmd = ["herdr", "agent", "get", agent_id]
            herdr_agent_name = agent_id  # Use raw ID

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output_text = result.stdout
            error_text = result.stderr
            success = result.returncode == 0
            return {
                "agent_id": agent_id,
                "herdr_agent_name": herdr_agent_name,
                "output": output_text,
                "error": error_text if not success else None,
                "success": success,
                "paperclip_online": self.check_paperclip_online()
            }
        except subprocess.TimeoutExpired:
            return {
                "agent_id": agent_id,
                "error": "Timeout reading agent output from Herdr",
                "success": False
            }
        except Exception as e:
            return {
                "agent_id": agent_id,
                "error": str(e),
                "success": False
            }

    def derive_herdr_agent_name(self, agent_id: str) -> Optional[str]:
        """Try to derive Herdr agent name from Paperclip agent_id."""
        # This is a placeholder. In practice you'd reverse-lookup from Herdr's agent table.
        return agent_id

    def handle_agent_prompt(self, agent_id: str) -> None:
        """Submit a manual prompt to the agent."""
        # This is a placeholder; you'd use herdr agent prompt or herdr pane send-text
        self.send_json({
            "agent_id": agent_id,
            "status": "not_implemented_yet",
            "message": "Manual prompt submission is not yet implemented. Use heartbeats or the UI."
        })

    def send_html_index(self) -> None:
        """Serve the dashboard HTML."""
        html_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))


def main():
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8000"))
    print(f"Dashboard backend listening on {host}:{port} (Paperclip API: {PAPERCLIP_URL})")
    server = HTTPServer((host, port), DashboardHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
