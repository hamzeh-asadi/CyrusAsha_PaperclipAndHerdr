#!/usr/bin/env python3
"""
Backend server for Paperclip+Herdr unified dashboard.
Company roster, Herdr handoffs, task decomposition, and human review.
"""

import argparse
import json
import os
import re
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote, urlencode, urlparse

from desk_text import Message, error_detail, preferred_language
from paperclip_client import PaperclipError, PaperclipConnectionError, is_loopback, request_json
from herdr_worker import bound_agent, cli_text, live_sessions, safe_session, safe_target
import team_desk as desk

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


def paperclip_json(path: str, method: str = "GET", timeout: float = 5, *, base_url: Optional[str] = None,
                   data: Optional[dict] = None) -> Any:
    return request_json(base_url if base_url is not None else PAPERCLIP_URL, path, method, timeout,
                        key=PAPERCLIP_API_KEY if base_url is None else "", data=data)


def paperclip_health_state(base_url: Optional[str] = None, timeout: float = 3) -> str:
    """One public readiness probe, shared by the Windows launcher and the dashboard."""
    try:
        data = paperclip_json("/api/health", timeout=timeout, base_url=base_url)
    except PaperclipConnectionError as exc:
        return exc.state
    if not isinstance(data, dict) or data.get("status") not in ("ok", "starting"):
        raise PaperclipError(Message("err.health"))
    return data["status"]


def check_paperclip_online() -> bool:
    """Service readiness is independent of companies, agents and board credentials."""
    try:
        return paperclip_health_state() == "ok"
    except (PaperclipError, ValueError):
        return False


def resolve_company() -> dict:
    if COMPANY_ID:
        # Some collection endpoints return [] even for an unknown company.
        try:
            company = paperclip_json(f"/api/companies/{quote(COMPANY_ID, safe='')}")
        except PaperclipError as exc:
            if exc.status != 404:
                raise
            company = None
        if not isinstance(company, dict) or company.get("id") != COMPANY_ID:
            raise PaperclipError(Message("err.unknownCompany"), 409)
        return company

    companies = paperclip_json("/api/companies")
    if not isinstance(companies, list):
        raise PaperclipError(Message("err.companyList"))
    if not companies:
        raise PaperclipError(Message("err.createCompany", url=PAPERCLIP_URL), 409)
    if len(companies) > 1:
        raise PaperclipError(Message("err.chooseCompany"), 409)
    company = companies[0]
    if not isinstance(company, dict) or not isinstance(company.get("id"), str) or not company["id"]:
        raise PaperclipError(Message("err.companyId"))
    return company


def resolve_company_id() -> str:
    return resolve_company()["id"]


def company_collection(collection: str) -> list:
    company_id = quote(resolve_company_id(), safe="")
    rows = paperclip_json(f"/api/companies/{company_id}/{collection}")
    if not isinstance(rows, list):
        raise PaperclipError(Message("err.list"))
    return rows


def list_agents_from_paperclip() -> Dict[str, Any]:
    company = resolve_company()
    rows = desk.roster(paperclip_json, company["id"])
    summaries = [desk.agent_summary(a) for a in rows]
    mapping = parse_agent_map(HERDR_AGENT_MAP)
    for member in summaries:
        if mapping and mapped_output(member, mapping):
            member['hasOutputMapping'] = True
    return {"agents": summaries, "paperclip_online": True,
            "company": {"id": company["id"], "name": company.get("name", ""), "issuePrefix": company.get("issuePrefix")}}


# --- Herdr agent mapping -----------------------------------------------------

_herdr_agents_cache: Dict[str, Any] = {"at": 0.0, "agents": None}


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

    agents = desk.live_targets()
    _herdr_agents_cache.update(at=now, agents=agents)
    return agents


def _name_candidates(name: Optional[str]) -> set:
    """Name forms to compare, ignoring a trailing role word (Worker, Coder, ...)."""
    if not name:
        return set()
    normalized = _normalize_agent_key(name)
    root = re.sub(r"-(worker|coder|agent|bot)$", "", normalized)
    return {value for value in (normalized, root) if value}


def mapped_output(record, mapping):
    names = _name_candidates(record.get('name'))
    for key in [_normalize_agent_key(record['id']), *sorted(names, key=len, reverse=True)]:
        if key in mapping:
            return mapping[key]
    return None


def output_target(record):
    """Desk members only expose the chosen agent. Legacy maps are for reading, never dispatch."""
    link = desk.connection(record)
    if link:
        if link['mode'] == 'manual':
            raise PaperclipError(Message("err.manualOutput"), 409)
        binding = record['metadata']['herdrDesk']
        bound_agent(link['target'], binding.get('terminal'), binding.get('kind'), link.get('session'))
        return link['target'], link.get('session')
    if mapped := mapped_output(record, parse_agent_map(HERDR_AGENT_MAP)):
        return mapped, None
    if record.get('adapterType') in ('hermes_local', 'hermes_gateway'):
        raise PaperclipError(Message("err.hermesOutput"), 409)
    names = _name_candidates(record.get('name'))
    live = list_herdr_agents()
    matches = {row['target'] for row in live if names & _name_candidates(row.get('name'))
               or record['id'] in (row['target'], row.get('pane_id'))}
    if len(matches) == 1:
        return matches.pop(), None
    raise PaperclipError(Message("err.outputMap"), 409)


# Only these known repository files are served; no generic file-system route.
STATIC_TYPES = {
    "/strings.json": "application/json",
    "/i18n.js": "application/javascript",
    "/desk.js": "application/javascript",
    "/desk.css": "text/css",
    "/brand/desk-mark.png": "image/png",
    "/fonts/vazirmatn-arabic.woff2": "font/woff2",
    "/fonts/OFL.txt": "text/plain",
}

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler exposing dashboard APIs."""

    def log_message(self, format, *args):
        # Disable default logging
        pass

    def send_json(self, data: Any, status: int = 200, *, lang: Optional[str] = None):
        """Helper to send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if lang:
            self.send_header("Content-Language", lang)
            self.send_header("Vary", "Accept-Language")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def send_error_json(self, message, status: int = 500):
        """Helper to send JSON error."""
        detail = error_detail(message)
        if isinstance(detail, Message):
            lang = preferred_language(self.headers.get("Accept-Language", ""))
            self.send_json({"error": detail.render(lang), "i18n": detail.wire()}, status, lang=lang)
        else:
            self.send_json({"error": str(detail)}, status)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        # A loopback-only desk must not expose private board reads to rebound hostnames.
        if parsed.path.startswith('/api/') and is_loopback(self.server.server_address[0]) and not self.is_local_operator():
            self.send_error_json(Message("err.local"), 403)
            return
        if parsed.path in STATIC_TYPES:
            self.send_asset(parsed.path[1:], STATIC_TYPES[parsed.path])
            return
        if parsed.path in ('/api/herdr/targets', '/api/herdr/sessions'):
            if not self.is_local_operator():
                self.send_error_json(Message("err.localTargets"), 403)
                return
            try:
                if parsed.path.endswith('/sessions'):
                    self.send_json({'sessions': live_sessions()})
                else:
                    params = parse_qs(parsed.query, keep_blank_values=True)
                    names = params.get('session', [None])
                    if len(names) != 1 or (names[0] is not None and not safe_session(names[0])):
                        self.send_error_json(Message("err.sessionName"), 400)
                        return
                    self.send_json({'targets': desk.live_targets(names[0])})
            except (ValueError, TypeError, RuntimeError) as exc:
                self.send_error_json(exc, 503)
            return
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
            self.send_error_json(Message("err.notFound"), status=404)

    def do_POST(self):
        parsed = urlparse(self.path)

        # This local dashboard uses server-side credentials. Only same-origin
        # browser requests (or a non-browser client) may trigger actions.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "").lower()
        if self.headers.get("Sec-Fetch-Site") == "cross-site" or (
            origin and origin.lower() not in (f"http://{host}", f"https://{host}")
        ):
            self.send_error_json(Message("err.origin"), status=403)
            return

        if not self.is_local_operator():
            self.send_error_json(Message("err.localWrite"), 403)
            return
        if parsed.path in ('/api/team/enroll', '/api/plans', '/api/work/advance'):
            try:
                data = self.read_json_object()
                company = resolve_company_id()
                if data.get('companyId') != company:
                    raise PaperclipError(Message("err.companyChanged"), 409)
                if parsed.path == '/api/team/enroll':
                    if not is_loopback(urlparse(PAPERCLIP_URL).hostname or ''):
                        raise PaperclipError(Message("err.localHire"), 409)
                    result = desk.enroll(paperclip_json, company, data)
                elif parsed.path == '/api/plans':
                    result = desk.save_plan(paperclip_json, company, data)
                else:
                    result = desk.advance(paperclip_json, company, data)
                self.send_json(result)
            except PaperclipError as exc:
                self.send_error_json(exc, exc.status)
            return
        # Trigger heartbeat manually via POST
        if parsed.path.startswith("/api/agents/") and parsed.path.endswith("/heartbeat/invoke"):
            agent_id = parsed.path[len("/api/agents/"):-len("/heartbeat/invoke")]
            self.handle_heartbeat(agent_id, {})
        else:
            self.send_error_json(Message("err.notFound"), status=404)

    def is_local_operator(self):
        # A DNS-rebound hostname or a network/proxy client is not a local operator.
        # Do not trust X-Forwarded-* headers in this unauthenticated application.
        try:
            host = urlparse('//' + self.headers.get('Host', '')).hostname or ''
            return is_loopback(host) and is_loopback(self.client_address[0])
        except ValueError:
            return False

    def read_json_object(self):
        if self.headers.get_content_type() != 'application/json':
            raise PaperclipError(Message("err.media"), 415)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 128 * 1024:
                raise PaperclipError(Message("err.size"), 413)
            value = json.loads(self.rfile.read(size).decode('utf-8'))
        except (ValueError, RecursionError):
            raise PaperclipError(Message("err.json"), 400) from None
        if not isinstance(value, dict):
            raise PaperclipError(Message("err.object"), 400)
        return value

    def check_paperclip_online(self) -> bool:
        """Delegate to the module-level helper (kept as a method for existing callers)."""
        return check_paperclip_online()

    def handle_agents(self, query: Dict[str, list]) -> None:
        """List all agents from Paperclip."""
        try:
            agents = self.list_agents_from_paperclip()
            agents["localControl"] = self.is_local_operator()
            prefix = agents['company'].get('issuePrefix')
            if prefix and agents['localControl']:
                # Top-level navigation to the actual board, never an XHR or a credential-bearing link.
                agents['company']['boardUrl'] = PAPERCLIP_URL + '/' + quote(prefix, safe='')
            self.send_json(agents)
        except PaperclipError as e:
            self.send_error_json(e, status=e.status)
        except Exception as e:
            self.send_error_json(e, status=500)

    def list_agents_from_paperclip(self) -> Dict[str, Any]:
        """Delegate to the module-level helper (kept as a method for existing callers)."""
        return list_agents_from_paperclip()

    def handle_heartbeat(self, agent_id: str, query: Dict[str, list]) -> None:
        """Trigger a heartbeat for the specified agent."""
        try:
            result = self.trigger_heartbeat(agent_id)
            self.send_json(result)
        except PaperclipError as e:
            self.send_error_json(e, status=e.status)
        except Exception as e:
            self.send_error_json(e, status=500)

    def trigger_heartbeat(self, agent_id: str) -> Dict[str, Any]:
        """Call Paperclip's heartbeat endpoint for the agent."""
        agent = next((a for a in self.list_agents_from_paperclip()['agents'] if a['id'] == agent_id), None)
        if not agent:
            raise PaperclipError(Message("err.agent"), 404)
        if (agent.get('connection') or {}).get('mode') == 'manual':
            raise PaperclipError(Message("err.manualWake"), 409)
        if agent.get('assignable') is False:
            raise PaperclipError(Message("err.notReady"), 409)
        resp = paperclip_json(f"/api/agents/{quote(agent_id, safe='')}/heartbeat/invoke", method="POST")
        return {"agent_id": agent_id, "status": "triggered", "response": {k: resp.get(k) for k in ("id", "status")} if isinstance(resp, dict) else {}}

    def handle_tickets(self, query: Dict[str, list]) -> None:
        """List tickets (optional filter by agent)."""
        try:
            tickets = self.list_tickets_from_paperclip(query)
            self.send_json(tickets)
        except PaperclipError as e:
            self.send_error_json(e, status=e.status)
        except Exception as e:
            self.send_error_json(e, status=500)

    def list_tickets_from_paperclip(self, query: Dict[str, list]) -> Dict[str, Any]:
        """Fetch tickets from Paperclip API."""
        assignee = query.get("assigneeAgentId", [""])[0] if query.get("assigneeAgentId") else ""
        status = query.get("status", ["backlog,todo,in_progress,in_review,blocked"])[0]
        params = {"status": status}
        if assignee:
            params["assigneeAgentId"] = assignee
        data = company_collection(f"issues?{urlencode(params)}")
        return {"tickets": [desk.issue_summary(t) for t in data], "paperclip_online": True}

    def handle_agent_output(self, agent_id: str, query: Dict[str, list]) -> None:
        """Get recent output for the specified agent from Herdr."""
        if not self.is_local_operator():
            self.send_error_json(Message("err.localOutput"), 403)
            return
        try:
            member = next((row for row in desk.roster(paperclip_json, resolve_company_id()) if row['id'] == agent_id), None)
            if not member:
                raise PaperclipError(Message("err.agent"), 404)
            lines = query.get('lines', ['120'])[0]
            source = query.get('source', ['recent-unwrapped'])[0]
            if not lines.isdecimal() or len(lines) > 3 or not 1 <= int(lines) <= 200 or source not in ('recent-unwrapped', 'visible'):
                raise PaperclipError(Message("err.outputArgs"), 400)
            target, session = output_target(member)
            if not safe_target(target):
                raise PaperclipError(Message("err.target"), 400)
            output = cli_text('agent', 'read', target, f'--source={source}', f'--lines={lines}',
                              session=session)
            self.send_json({'agent_id': agent_id, 'herdr_agent_name': target, 'output': output, 'success': True})
        except PaperclipError as exc:
            self.send_error_json(exc, exc.status)
        except ValueError as exc:
            self.send_error_json(exc, 400)
        except RuntimeError as exc:
            self.send_error_json(exc, 503)

    def send_html_index(self) -> None:
        """Serve the dashboard HTML."""
        self.send_asset('index.html', 'text/html')

    def send_asset(self, name, mime):
        # All names come from the fixed route table, never from a request path.
        body = (Path(__file__).parent / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime if mime.startswith(('font/', 'image/')) else mime + '; charset=utf-8')
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)


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
