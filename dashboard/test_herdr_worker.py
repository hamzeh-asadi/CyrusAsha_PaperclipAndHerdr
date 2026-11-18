"""Worker contract, with run credentials and Herdr both simulated (no live agents)."""

import os
import subprocess
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import herdr_worker as worker
from paperclip_client import PaperclipError


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.issue = {
            "id": "i",
            "companyId": "c",
            "assigneeAgentId": "a",
            "status": "todo",
            "title": "تست",
            "description": "two\nlines",
        }
        self.session = {
            "name": "my-agy",
            "agent": "agy",
            "agent_status": "idle",
            "terminal_id": "t1",
            "interactive_ready": True,
        }
        self.wake = dict(
            id="run1", companyId="c", agentId="a", invocationSource="on_demand", triggerDetail="manual"
        )
        self.checkout = None
        self.end = dict(self.session)
        self.calls, self.cli = [], []

        def board(url, path, method, **kwargs):
            self.assertEqual((url, kwargs["key"], kwargs["run_id"]), ("http://board", "run-only", "run1"))
            self.calls.append((method, path, kwargs["data"]))
            if path == "/api/heartbeat-runs/run1":
                return self.wake
            if method == "GET" and path.startswith("/api/issues/"):
                return self.issue
            if path.startswith("/api/companies/c/issues?"):
                return [{"id": "wrong", "companyId": "c", "assigneeAgentId": "b", "status": "todo"}, self.issue]
            if path.endswith("/checkout"):
                if self.checkout:
                    raise self.checkout
                return dict(self.issue, status="in_progress", checkoutRunId="run1")
            if path.endswith("/interactions"):
                return {"status": "pending", "id": "confirmation"}
            if method == "PATCH":
                return dict(self.issue, **kwargs["data"])
            return {}

        def herdr(*cmd, **kw):
            self.cli.append(cmd)
            if cmd[:2] == ("agent", "get"):
                return {"agent": self.session}
            if cmd[:2] == ("agent", "prompt"):
                return {"agent": self.end}
            self.fail(f"Unexpected Herdr command: {cmd[:2]}")

        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(
                    os.environ,
                    dict(
                        PAPERCLIP_COMPANY_ID="c",
                        PAPERCLIP_AGENT_ID="a",
                        PAPERCLIP_RUN_ID="run1",
                        PAPERCLIP_API_URL="http://board",
                        PAPERCLIP_API_KEY="run-only",
                    ),
                    clear=True,
                )
            )
            stack.enter_context(patch.object(worker, "request_json", board))
            stack.enter_context(patch.object(worker, "herdr", herdr))
            self.addCleanup(stack.pop_all().close)

    def run_worker(self):
        worker.run("my-agy", "", "agy")

    def test_handoff_exact_target_and_pending_human_review(self):
        self.run_worker()
        self.assertEqual(self.cli[1][:3], ("agent", "prompt", "my-agy"))
        self.assertNotIn("\n", self.cli[1][3])
        self.assertIn("تست", self.cli[1][3])
        self.assertEqual(self.calls[2][1], "/api/issues/i/checkout")
        self.assertEqual(self.calls[-2][2]["continuationPolicy"], "none")
        self.assertEqual(self.calls[-1][2]["reviewInteractionId"], "confirmation")
        self.assertEqual(self.calls[-1][2]["status"], "in_review")

    def test_mismatched_wake_or_old_checkout_is_not_redispatched(self):
        with patch.dict(os.environ, {"PAPERCLIP_TASK_ID": "different"}):
            self.run_worker()
        self.issue.update(status="in_progress", checkoutRunId="another-run")
        self.run_worker()
        self.assertFalse(self.cli)
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))
        self.issue["checkoutRunId"] = "run1"
        self.run_worker()
        self.assertFalse(any(path.endswith("/checkout") for _, path, _ in self.calls))

    def test_scoped_wake_not_in_env_and_uncertain_previous_run(self):
        self.wake.update(issueId="i", invocationSource="automation", triggerDetail="system")
        self.run_worker()
        self.assertEqual(self.calls[1][:2], ("GET", "/api/issues/i"))
        self.cli.clear()
        self.wake.update(retryOfRunId="older")
        with self.assertRaisesRegex(RuntimeError, "earlier attempt"):
            self.run_worker()
        self.assertFalse(self.cli)

    def test_conflict_or_denied_checkout_never_sends_text(self):
        self.checkout = PaperclipError("claimed", 409)
        self.run_worker()
        self.checkout = PaperclipError("not allowed", 403)
        with self.assertRaises(PaperclipError):
            self.run_worker()
        self.assertTrue(all(cmd[:2] == ("agent", "get") for cmd in self.cli))

    def test_failed_review_bookkeeping_and_uncertain_cli_never_repeat_prompt(self):
        with patch.object(worker, "request_human_review", side_effect=PaperclipError("write failed", 502)):
            with self.assertRaisesRegex(RuntimeError, "do NOT repeat"):
                self.run_worker()
        self.assertEqual(sum(cmd[:2] == ("agent", "prompt") for cmd in self.cli), 1)
        with patch.object(
            worker, "herdr", side_effect=[{"agent": self.session}, RuntimeError("timeout")]
        ) as cli:
            with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                self.run_worker()
            self.assertEqual(cli.call_count, 2)
        self.assertFalse(any(path.endswith("/interactions") for _, path, _ in self.calls))

    def test_unready_changed_or_blocked_target_never_advanced(self):
        self.end["agent_status"] = "blocked"
        with self.assertRaises(RuntimeError):
            self.run_worker()
        self.assertFalse(any(method == "PATCH" for method, _, _ in self.calls))
        self.cli.clear()
        self.session["interactive_ready"] = False
        with self.assertRaises(RuntimeError):
            self.run_worker()
        self.assertEqual(len(self.cli), 1)
        with self.assertRaises(RuntimeError):
            worker.run("w1:p1", "stale-terminal-id", "agy")
        with self.assertRaises(ValueError):
            worker.run("--wrong", "", "agy")


class DiscoveryTests(unittest.TestCase):
    def test_only_detected_unique_target_forms_can_be_bound(self):
        base = dict(agent="agy", pane_id="w1:p1", terminal_id="term-1", display_agent="Label")
        with patch.object(
            worker,
            "herdr",
            return_value={
                "agents": [
                    dict(base, name="worker"),
                    base,
                    dict(base, terminal_id=None),
                    dict(base, agent=None),
                    dict(base, name="--flag"),
                ]
            },
        ):
            self.assertEqual(
                [(t["target"], t["terminal"]) for t in worker.live_targets()],
                [("worker", ""), ("w1:p1", "term-1")],
            )

    def test_herdr_subprocess_gets_no_paperclip_credentials(self):
        with (
            patch.dict(os.environ, {"PAPERCLIP_API_KEY": "test-secret"}),
            patch.object(worker.shutil, "which", return_value="herdr"),
            patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, '{"result":{"agents":[]}}', ""),
            ) as cmd,
        ):
            worker.live_targets()
            self.assertEqual(cmd.call_args.args[0], ["herdr", "agent", "list"])
            self.assertNotIn("PAPERCLIP_API_KEY", cmd.call_args.kwargs["env"])

    def test_manual_worker_does_not_need_any_cli_or_key(self):
        result = subprocess.run(
            [sys.executable, worker.__file__, "manual"], capture_output=True, text=True, timeout=5
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No prompt sent", result.stdout)
