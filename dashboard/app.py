#!/usr/bin/env python3
"""
Backend server for Paperclip+Herdr unified dashboard.
Scans agents, triggers heartbeats, lists tickets, and fetches recent agent output.
"""

import argparse
import ipaddress
import json
import os
import re
import subprocess
import time
import urllib.request
import webbrowser
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional
from urllib.error import HTTPError as UrllibHTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env_file(path: str) -> None:
    """Load KEY=VALUE pairs from a .env file.

    The .env file always wins over existing environment variables so that
    the dashboard configuration is deterministic regardless of shell state.
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
            if key:
                os.environ[key] = value.strip().strip('"').strip("'")


load_env_file(ENV_FILE)

# Configuration
PAPERCLIP_URL = (os.getenv("PAPERCLIP_API_URL") or "http://localhost:3100").strip().rstrip("/")
COMPANY_ID = os.getenv("PAPERCLIP_COMPANY_ID", "").strip()
PAPERCLIP_API_KEY = os.getenv("PAPERCLIP_API_KEY", "").strip()
# Explicit Paperclip -> Herdr mapping for agents whose names differ, e.g.
#   HERDR_AGENT_MAP=856affb4-...=agy-worker,Freebuff-Coder=w2:p1
# Keys may be a Paperclip agent id or agent name; values are Herdr names or pane ids.
HERDR_AGENT_MAP = os.getenv("HERDR_AGENT_MAP", "")
HERDR_CACHE_TTL = float(os.getenv("HERDR_CACHE_TTL", "10"))
PAPERCLIP_AGENT_CACHE_TTL = float(os.getenv("PAPERCLIP_AGENT_CACHE_TTL", "30"))


class PaperclipError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class PaperclipConnectionError(PaperclipError):
    """A retryable transport failure, not an HTTP/authentication error."""

    def __init__(self, state: str):
        self.state = state
        super().__init__(f"Paperclip connection {state}. Check PAPERCLIP_API_URL and the npm start terminal.", 503)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # An API response must be JSON, not a login page. Never forward a bearer
    # token to a redirect target.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_api = urllib.request.build_opener(_NoRedirect())
_direct_api = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _is_loopback(host: str) -> bool:
    if host.rstrip(".").lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def paperclip_json(path: str, method: str = "GET", timeout: float = 5, *, base_url: Optional[str] = None) -> Any:
    url = (base_url if base_url is not None else PAPERCLIP_URL).rstrip("/")
    headers = {"Accept": "application/json"}
    if PAPERCLIP_API_KEY and base_url is None and path != "/api/health":
        headers["Authorization"] = f"Bearer {PAPERCLIP_API_KEY}"
    try:
        base = urlparse(url)
        if (base.scheme not in ("http", "https") or not base.hostname or base.username is not None
                or base.query or base.fragment):
            raise ValueError("invalid base URL")
        req = urllib.request.Request(f"{url}{path}", headers=headers, method=method)
    except ValueError as exc:
        raise PaperclipError("PAPERCLIP_API_URL must be an HTTP(S) base URL without credentials, query or fragment.") from exc
    try:
        # Never send loopback traffic (including board credentials) to a system proxy.
        opener = _direct_api if _is_loopback(base.hostname) else _api
        with opener.open(req, timeout=timeout) as response:
            return json.load(response)
    except UrllibHTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise PaperclipError(
                f"Paperclip HTTP {exc.code}: check PAPERCLIP_API_KEY and its permissions.", exc.code
            ) from exc
        status = exc.code if 400 <= exc.code < 500 else 502
        raise PaperclipError(f"Paperclip returned HTTP {exc.code} for {path}.", status) from exc
    except (URLError, OSError, HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, ConnectionRefusedError):
            raise PaperclipConnectionError("refused") from exc
        if isinstance(reason, TimeoutError):
            raise PaperclipConnectionError("timeout") from exc
        raise PaperclipError("Cannot reach Paperclip. Check PAPERCLIP_API_URL and the npm start terminal.", 503) from exc
    except ValueError as exc:
        raise PaperclipError("Expected JSON from Paperclip. Check PAPERCLIP_API_URL (base URL without /api).") from exc


def paperclip_health_state(base_url: Optional[str] = None, timeout: float = 3) -> str:
    """One public readiness probe, shared by the Windows launcher and the dashboard."""
    try:
        data = paperclip_json("/api/health", timeout=timeout, base_url=base_url)
    except PaperclipConnectionError as exc:
        return exc.state
    if not isinstance(data, dict) or data.get("status") not in ("ok", "starting"):
        raise PaperclipError("Unexpected /api/health response. Check the Paperclip URL and port.")
    return data["status"]


def check_paperclip_online() -> bool:
    """Service readiness is independent of companies, agents and board credentials."""
    try:
        return paperclip_health_state() == "ok"
    except (PaperclipError, ValueError):
        return False


def resolve_company_id() -> str:
    if COMPANY_ID:
        # Some collection endpoints return [] even for an unknown company.
        try:
            company = paperclip_json(f"/api/companies/{quote(COMPANY_ID, safe='')}")
        except PaperclipError as exc:
            if exc.status != 404:
                raise
            company = None
        if not isinstance(company, dict) or company.get("id") != COMPANY_ID:
            raise PaperclipError(
                "Unknown PAPERCLIP_COMPANY_ID. Clear or correct it in dashboard/.env and restart the dashboard.", 409
            )
        return COMPANY_ID

    companies = paperclip_json("/api/companies")
    if not isinstance(companies, list):
        raise PaperclipError("Expected a company list from Paperclip.")
    if not companies:
        raise PaperclipError(f"Create a company in Paperclip ({PAPERCLIP_URL}); the dashboard will retry automatically.", 409)
    if len(companies) > 1:
        raise PaperclipError(
            "Multiple companies. Choose an id from /api/companies, set PAPERCLIP_COMPANY_ID "
            "in dashboard/.env and restart the dashboard.", 409
        )
    company = companies[0]
    if not isinstance(company, dict) or not isinstance(company.get("id"), str) or not company["id"]:
        raise PaperclipError("Paperclip returned a company without an id.")
    return company["id"]


def company_collection(collection: str) -> list:
    company_id = quote(resolve_company_id(), safe="")
    rows = paperclip_json(f"/api/companies/{company_id}/{collection}")
    if not isinstance(rows, list):
        raise PaperclipError("Expected a list from the Paperclip API.")
    return rows


def list_agents_from_paperclip() -> Dict[str, Any]:
    return {"agents": company_collection("agents"), "paperclip_online": True}


# --- Herdr agent mapping -----------------------------------------------------

_herdr_agents_cache: Dict[str, Any] = {"at": 0.0, "agents": None}
_paperclip_agents_cache: Dict[str, Any] = {"at": 0.0, "agents": {}}


def _normalize_agent_key(value: str) -> str:
    """Lowercase a name/id and collapse every non-alphanumeric run into one dash."""
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def parse_agent_map(raw: str) -> Dict[str, str]:
    """Parse HERDR_AGENT_MAP into {normalized key: Herdr target}.

    Accepts comma, semicolon or newline separated ``key=target`` pairs. Keys are
    Paperclip agent ids or agent names, values are Herdr agent names or pane ids
    such as ``w1:p2`` (the two target forms Herdr itself accepts).
    """
    mapping: Dict[str, str] = {}
    for chunk in re.split(r"[,;\n]+", raw or ""):
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#") or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key = _normalize_agent_key(key)
        value = value.strip()
        if key and value:
            mapping[key] = value
    return mapping


def _find_agent_list(payload: Any) -> Optional[list]:
    """Find the agent array inside an unknown Herdr response wrapper."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("agents", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
        for value in payload.values():
            found = _find_agent_list(value)
            if found is not None:
                return found
    return None


def list_herdr_agents(use_cache: bool = True) -> list:
    """Return the live Herdr agents as {name, target, pane_id, status} dicts.

    ``target`` is what ``herdr agent read`` accepts: the unique live agent name,
    or the pane id for agents that were launched manually (Herdr leaves those
    unnamed). Raises when the Herdr CLI is missing or the server is unreachable;
    callers decide how to report that.
    """
    now = time.time()
    if (
        use_cache
        and _herdr_agents_cache["agents"] is not None
        and now - _herdr_agents_cache["at"] < HERDR_CACHE_TTL
    ):
        return _herdr_agents_cache["agents"]  # type: ignore[return-value]

    proc = subprocess.run(
        ["herdr", "agent", "list"], capture_output=True, text=True, timeout=10
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or "herdr agent list failed")
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    records = _find_agent_list(payload) or []

    agents = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = record.get("name") or record.get("agent_name") or record.get("display_agent")
        pane_id = record.get("pane_id")
        if not pane_id and isinstance(record.get("pane"), dict):
            pane_id = record["pane"].get("pane_id")
        if not name and isinstance(record.get("agent"), dict):
            name = record["agent"].get("name")
        status = record.get("agent_status") or record.get("status") or record.get("state")
        target = name or pane_id
        if not target:
            continue
        agents.append(
            {"name": name, "target": target, "pane_id": pane_id, "status": status}
        )

    _herdr_agents_cache.update(at=now, agents=agents)
    return agents


def _paperclip_agent_record(agent_id: str) -> Optional[Dict[str, Any]]:
    """Look up one Paperclip agent (cached) so its name can be matched to Herdr."""
    now = time.time()
    cache = _paperclip_agents_cache
    if not cache["agents"] or now - cache["at"] >= PAPERCLIP_AGENT_CACHE_TTL:
        records: list = []
        try:
            payload = list_agents_from_paperclip().get("agents")
            found = _find_agent_list(payload)
            records = found if isinstance(found, list) else []
        except Exception:
            # Paperclip offline: the explicit map and the raw-id check still work.
            records = []
        cache.update(
            at=now,
            agents={
                str(record.get("id")): record
                for record in records
                if isinstance(record, dict) and record.get("id")
            },
        )
    return cache["agents"].get(agent_id)  # type: ignore[union-attr]


def _name_candidates(name: Optional[str]) -> set:
    """Name forms to compare, ignoring a trailing role word (Worker, Coder, ...)."""
    if not name:
        return set()
    normalized = _normalize_agent_key(name)
    root = re.sub(r"-(worker|coder|agent|bot)$", "", normalized)
    return {value for value in (normalized, root) if value}


def derive_herdr_agent_name(agent_id: str) -> Optional[str]:
    """Resolve a Paperclip agent id to a Herdr target (agent name or pane id).

    Order: explicit HERDR_AGENT_MAP entry (by id, then by Paperclip agent name),
    then a match against the live ``herdr agent list`` names, then the id itself
    when Herdr already uses it (a pane id or a live agent name). Returns None when
    nothing matches, so the caller can report an actionable error instead of
    asking Herdr for a Paperclip UUID that Herdr has never seen.
    """
    mapping = parse_agent_map(HERDR_AGENT_MAP)

    explicit = mapping.get(_normalize_agent_key(agent_id))
    if explicit:
        return explicit

    record = _paperclip_agent_record(agent_id) or {}
    agent_name = record.get("name") or record.get("title")
    wanted = _name_candidates(agent_name)

    for candidate in sorted(wanted, key=len, reverse=True):
        if candidate in mapping:
            return mapping[candidate]

    try:
        live_agents = list_herdr_agents()
    except Exception:
        live_agents = []

    for agent in live_agents:
        if wanted and wanted & _name_candidates(agent.get("name")):
            return agent["target"]

    for agent in live_agents:
        if agent_id in (agent.get("target"), agent.get("pane_id")):
            return agent_id

    return None


def missing_herdr_target_message(agent_id: str) -> str:
    """Explain how to map an unmapped Paperclip agent to a Herdr target."""
    record = _paperclip_agent_record(agent_id) or {}
    agent_name = record.get("name") or "unknown"
    try:
        targets = [agent["target"] for agent in list_herdr_agents()]
    except FileNotFoundError:
        return (
            "Herdr CLI ('herdr') is not in PATH, so agent output cannot be read. "
            "Install Herdr or add it to PATH, then reload."
        )
    except Exception as exc:
        return f"Herdr is not reachable: {exc}"

    if not targets:
        return (
            "Herdr has no live agents. Start the agent in Herdr (herdr agent start "
            f"<name> --kind <kind> --pane <pane>) or run it in a pane, then reload. "
            f"Paperclip agent: {agent_name} ({agent_id})."
        )
    return (
        f"No Herdr target is mapped to Paperclip agent {agent_name} ({agent_id}). "
        "Add it to dashboard/.env as HERDR_AGENT_MAP=<paperclip-id>=<herdr-name> "
        "(several pairs separated by commas). "
        f"Live Herdr targets: {', '.join(targets)}."
    )


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

        # This local dashboard uses server-side credentials. Only same-origin
        # browser requests (or a non-browser client) may trigger actions.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "").lower()
        if self.headers.get("Sec-Fetch-Site") == "cross-site" or (
            origin and origin.lower() not in (f"http://{host}", f"https://{host}")
        ):
            self.send_error_json("Cross-origin action denied", status=403)
            return

        # Trigger heartbeat manually via POST
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
        except PaperclipError as e:
            self.send_error_json(str(e), status=e.status)
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
        except PaperclipError as e:
            self.send_error_json(str(e), status=e.status)
        except Exception as e:
            self.send_error_json(str(e), status=500)

    def trigger_heartbeat(self, agent_id: str) -> Dict[str, Any]:
        """Call Paperclip's heartbeat endpoint for the agent."""
        resp = paperclip_json(f"/api/agents/{quote(agent_id, safe='')}/heartbeat/invoke", method="POST")
        return {"agent_id": agent_id, "status": "triggered", "response": resp}

    def handle_tickets(self, query: Dict[str, list]) -> None:
        """List tickets (optional filter by agent)."""
        try:
            tickets = self.list_tickets_from_paperclip(query)
            self.send_json(tickets)
        except PaperclipError as e:
            self.send_error_json(str(e), status=e.status)
        except Exception as e:
            self.send_error_json(str(e), status=500)

    def list_tickets_from_paperclip(self, query: Dict[str, list]) -> Dict[str, Any]:
        """Fetch tickets from Paperclip API."""
        assignee = query.get("assigneeAgentId", [""])[0] if query.get("assigneeAgentId") else ""
        status = query.get("status", ["todo,in_progress"])[0] if query.get("status") else "todo,in_progress"
        params = {"status": status}
        if assignee:
            params["assigneeAgentId"] = assignee
        data = company_collection(f"issues?{urlencode(params)}")
        return {"tickets": data, "paperclip_online": True}

    def handle_agent_output(self, agent_id: str, query: Dict[str, list]) -> None:
        """Get recent output for the specified agent from Herdr."""
        try:
            output = self.get_agent_output_from_herdr(agent_id, query)
            self.send_json(output)
        except PaperclipError as e:
            self.send_error_json(str(e), status=e.status)
        except Exception as e:
            self.send_error_json(str(e), status=500)

    def get_agent_output_from_herdr(self, agent_id: str, query: Dict[str, list]) -> Dict[str, Any]:
        """Read recent agent output via Herdr CLI."""
        lines = query.get("lines", ["120"])[0] if query.get("lines") else "120"
        source = query.get("source", ["recent-unwrapped"])[0] if query.get("source") else "recent-unwrapped"

        try:
            herdr_agent_name = self.derive_herdr_agent_name(agent_id)
        except Exception as e:
            return {
                "agent_id": agent_id,
                "herdr_agent_name": None,
                "output": "",
                "error": f"Could not resolve the Herdr target: {e}",
                "success": False,
                "paperclip_online": self.check_paperclip_online()
            }

        # Herdr only accepts a live agent name or a pane id as a target
        if not herdr_agent_name:
            return {
                "agent_id": agent_id,
                "herdr_agent_name": None,
                "output": "",
                "error": missing_herdr_target_message(agent_id),
                "success": False,
                "paperclip_online": self.check_paperclip_online()
            }

        cmd = ["herdr", "agent", "read", herdr_agent_name, f"--source={source}", f"--lines={lines}"]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output_text = result.stdout
            error_text = result.stderr
            success = result.returncode == 0
            return {
                "agent_id": agent_id,
                "herdr_agent_name": herdr_agent_name,
                "output": output_text,
                "error": error_text.strip() if not success and error_text.strip() else (None if success else "herdr agent read failed"),
                "success": success,
                "paperclip_online": self.check_paperclip_online()
            }
        except FileNotFoundError:
            return {
                "agent_id": agent_id,
                "herdr_agent_name": herdr_agent_name,
                "error": "Herdr CLI ('herdr') is not in PATH",
                "success": False
            }
        except subprocess.TimeoutExpired:
            return {
                "agent_id": agent_id,
                "herdr_agent_name": herdr_agent_name,
                "error": "Timeout reading agent output from Herdr",
                "success": False
            }
        except Exception as e:
            return {
                "agent_id": agent_id,
                "herdr_agent_name": herdr_agent_name,
                "error": str(e),
                "success": False
            }

    def derive_herdr_agent_name(self, agent_id: str) -> Optional[str]:
        """Delegate to the module-level resolver (kept as a method for existing callers)."""
        return derive_herdr_agent_name(agent_id)

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-browser", action="store_true", help="Open the dashboard after binding successfully")
    parser.add_argument("--probe-paperclip", metavar="URL", help="Print one readiness state without starting the dashboard")
    parser.add_argument("--probe-timeout", type=int, default=5, metavar="SECONDS")
    args = parser.parse_args()
    if args.probe_paperclip is not None:
        if not 1 <= args.probe_timeout <= 60:
            parser.error("--probe-timeout must be between 1 and 60 seconds")
        try:
            print(paperclip_health_state(args.probe_paperclip, args.probe_timeout))
        except (PaperclipError, ValueError) as exc:
            parser.exit(1, f"Paperclip probe failed: {exc}\n")
        return
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("DASHBOARD_PORT", "8000"))
        if not 0 <= port <= 65535:
            raise ValueError
    except ValueError:
        parser.error("DASHBOARD_PORT must be an integer between 0 and 65535")
    try:
        server = HTTPServer((host, port), DashboardHandler)
    except OSError as exc:
        parser.exit(1, f"Cannot bind the dashboard at {host}:{port}: {exc}. Check DASHBOARD_HOST and DASHBOARD_PORT.\n")
    with server:
        browse_host = "localhost" if host in ("", "0.0.0.0") else host
        url = f"http://{browse_host}:{server.server_port}"
        print(f"Dashboard: {url} (Paperclip API: {PAPERCLIP_URL})", flush=True)
        if args.open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
