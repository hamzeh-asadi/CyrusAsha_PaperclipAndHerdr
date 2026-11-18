#!/usr/bin/env python3
"""Offline regression tests: python -m unittest discover -s dashboard -v"""
import json
import os
import socket
import subprocess
import sys
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
import paperclip_client as transport


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
        status, data = self.request("/api/agents")
        self.assertEqual((status, data["agents"], data["company"]["id"]), (200, [], "only-company"))

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
        with patch.object(transport._direct_api, "open", side_effect=URLError(ConnectionRefusedError())):
            self.assertFalse(self.request("/health")[1]["paperclip"])
            self.assertEqual(self.request("/api/tickets")[0], 503)

    def test_launcher_uses_real_public_health_without_a_loopback_proxy(self):
        # The probe must honor the explicit URL even if dashboard/.env or the
        # shell config points elsewhere. A bad system proxy must not intercept it.
        url = f"http://localhost:{self.upstream.server_port}"
        env = dict(os.environ, PAPERCLIP_API_URL="http://127.0.0.1:1", PAPERCLIP_API_KEY="test-only",
                   http_proxy="http://127.0.0.1:1", HTTP_PROXY="http://127.0.0.1:1", NO_PROXY="", no_proxy="")
        for status, body, expected in [(200, {"status": "ok"}, "ok"), (200, {"status": "starting"}, "starting"),
                                       (403, {}, None), (200, b"<html>not the API</html>", None)]:
            with self.subTest(status=status, expected=expected):
                self.upstream.routes["GET", "/api/health"] = (status, body)
                result = subprocess.run([sys.executable, app.__file__, "--probe-paperclip", url],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0 if expected else 1, result.stderr)
                self.assertEqual(result.stdout.strip(), expected or "")
                self.assertEqual(self.upstream.requests[-1], ("GET", "/api/health", None))

    def test_health_distinguishes_absent_and_silent_listeners(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            self.assertEqual(app.paperclip_health_state(url, timeout=8), "refused")
            listener.listen()  # accepts a connection, never sends HTTP headers
            self.assertEqual(app.paperclip_health_state(url, timeout=.2), "timeout")

    def test_non_loopback_uses_normal_proxy_policy(self):
        with patch.object(transport._api, "open", side_effect=URLError(TimeoutError())) as remote:
            self.assertEqual(app.paperclip_health_state("https://paperclip.example"), "timeout")
            remote.assert_called_once()

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
