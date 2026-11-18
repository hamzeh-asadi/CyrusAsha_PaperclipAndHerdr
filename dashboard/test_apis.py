#!/usr/bin/env python3
"""Offline regression tests: python -m unittest discover -s dashboard -v"""
import json
import os
import tempfile
import threading
import unittest
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import app


@contextmanager
def serving(handler):
    with HTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.command, self.path, self.headers.get("Authorization")))
        status, body = self.server.routes.get((self.command, self.path), (404, {}))
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

    do_POST = do_GET

    def log_message(self, *args):
        pass


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ExitStack() as stack:
            cls.upstream = stack.enter_context(serving(Upstream))
            dashboard = stack.enter_context(serving(app.DashboardHandler))
            cls.dashboard_url = f"http://127.0.0.1:{dashboard.server_port}"
            stack.enter_context(patch.object(app, "PAPERCLIP_URL", f"http://127.0.0.1:{cls.upstream.server_port}"))
            stack.enter_context(patch.object(app, "COMPANY_ID", ""))
            stack.enter_context(patch.object(app, "PAPERCLIP_API_KEY", ""))
            cls.addClassCleanup(stack.pop_all().close)

    def setUp(self):
        self.upstream.requests = []
        self.upstream.routes = {("GET", "/api/health"): (200, {"status": "ok"})}

    def request(self, path, method="GET", headers=None):
        try:
            response = urlopen(Request(self.dashboard_url + path, method=method, headers=headers or {}), timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_new_instance_recovers_after_first_company_without_restart(self):
        self.upstream.routes["GET", "/api/companies"] = (200, [])
        self.assertEqual(self.request("/health"), (200, {"status": "ok", "paperclip": True}))
        status, data = self.request("/api/agents")
        self.assertEqual(status, 409)
        self.assertIn("Create a company", data["error"])
        self.upstream.routes.update({
            ("GET", "/api/companies"): (200, [{"id": "only-company"}]),
            ("GET", "/api/companies/only-company/agents"): (200, []),
        })
        self.assertEqual(self.request("/api/agents"), (200, {"agents": [], "paperclip_online": True}))

    def test_multiple_companies_require_a_choice(self):
        self.upstream.routes["GET", "/api/companies"] = (200, [{"id": "first"}, {"id": "second"}])
        status, data = self.request("/api/tickets")
        self.assertEqual(status, 409)
        self.assertIn("PAPERCLIP_COMPANY_ID", data["error"])
        self.assertEqual(len(self.upstream.requests), 1)

    def test_invalid_configured_id_is_not_an_offline_server_or_an_empty_company(self):
        with patch.object(app, "COMPANY_ID", "stale-id"):
            status, data = self.request("/api/agents")
            self.assertEqual(status, 409)
            self.assertIn("Unknown PAPERCLIP_COMPANY_ID", data["error"])
            self.assertTrue(self.request("/health")[1]["paperclip"])

    def test_scoped_gets_and_post_use_the_configured_key_server_side(self):
        self.upstream.routes.update({
            ("GET", "/api/companies/c2"): (200, {"id": "c2"}),
            ("GET", "/api/companies/c2/agents"): (200, [{"id": "worker"}]),
            ("GET", "/api/companies/c2/issues?status=todo&assigneeAgentId=worker"): (200, [{"id": "t1"}]),
            ("POST", "/api/agents/worker/heartbeat/invoke"): (202, {"id": "run"}),
        })
        with patch.object(app, "COMPANY_ID", "c2"), patch.object(app, "PAPERCLIP_API_KEY", "test-only"):
            self.assertEqual(self.request("/api/agents")[1]["agents"], [{"id": "worker"}])
            self.assertEqual(self.request("/api/tickets?assigneeAgentId=worker&status=todo")[1]["tickets"], [{"id": "t1"}])
            self.assertEqual(self.request("/api/agents/worker/heartbeat/invoke", "POST")[1]["status"], "triggered")
            self.assertTrue(all(auth == "Bearer test-only" for _, _, auth in self.upstream.requests))
            self.assertEqual(self.request("/health")[1], {"status": "ok", "paperclip": True})
            self.assertEqual(self.upstream.requests[-1], ("GET", "/api/health", None))

    def test_access_error_is_not_a_connection_error(self):
        for code in (401, 403):
            with self.subTest(code=code):
                self.upstream.routes["GET", "/api/companies"] = (code, {})
                status, data = self.request("/api/agents")
                self.assertEqual(status, code)
                self.assertIn("PAPERCLIP_API_KEY", data["error"])
                self.assertTrue(self.request("/health")[1]["paperclip"])

    def test_starting_wrong_service_and_unreachable_service(self):
        for body in ({"status": "starting"}, b"<html>not the API</html>"):
            self.upstream.routes["GET", "/api/health"] = (200, body)
            self.assertFalse(self.request("/health")[1]["paperclip"])
        with patch.object(app._api, "open", side_effect=URLError("connection refused")):
            self.assertFalse(self.request("/health")[1]["paperclip"])
            self.assertEqual(self.request("/api/tickets")[0], 503)

    def test_only_same_origin_post_can_wake_an_agent_from_a_browser(self):
        path = "/api/agents/worker/heartbeat/invoke"
        self.assertNotEqual(self.request(path)[0], 200)
        self.assertEqual(self.request(path, "POST", {"Origin": "https://other.example"})[0], 403)
        self.assertFalse(self.upstream.requests)

    def test_env_file_is_optional_and_bom_safe(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"DASHBOARD_PORT": "8000"}):
            path = Path(tmp) / ".env"
            app.load_env_file(path)
            path.write_text('DASHBOARD_PORT="8888"\n', encoding="utf-8-sig")
            app.load_env_file(path)
            self.assertEqual(os.environ["DASHBOARD_PORT"], "8888")


if __name__ == "__main__":
    unittest.main(verbosity=2)
