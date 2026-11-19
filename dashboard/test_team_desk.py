"""The desk persists its work through Paperclip, including approval and partial-write cases."""

import copy
import json
import sys
import unittest
import uuid
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
import team_desk as desk
from paperclip_client import PaperclipError
from test_apis import serving


class Board:
    def __init__(self):
        self.company = "c1"
        self.members = [
            {"id": v, "name": v, "status": "idle", "companyId": "c1"} for v in ["Freebuff", "agy"]
        ]
        self.issues, self.by_key, self.writes = {}, {}, []
        self.fail_title = None

    def __call__(self, path, method="GET", *, data=None):
        if method != "GET":
            self.writes.append((method, path, copy.deepcopy(data)))
        if path == "/api/companies":
            return [{"id": self.company, "name": "test"}]
        if path == "/api/companies/c1/agents":
            return self.members
        if path == "/api/companies/c1/agent-hires":
            r = {**data, "id": "new", "status": "pending_approval"}
            self.members.append(r)
            return {"agent": r, "approval": {"id": "vote"}}
        if path == "/api/companies/c1/issues" and method == "POST":
            if data["title"] == self.fail_title:
                raise PaperclipError("connection lost", 503)
            key = data["idempotencyKey"]
            if key not in self.by_key:
                i = str(len(self.by_key) + 1)
                self.issues[i] = {**data, "companyId": self.company, "id": i, "statusVersion": 1}
                self.by_key[key] = i
            return self.issues[self.by_key[key]]
        if path.startswith("/api/issues/"):
            i = path.split("/")[3]
            if method == "GET":
                return self.issues[i]
            if path.endswith("/interactions"):
                return {"status": "pending", "id": "decision"}
            if method == "PATCH":
                self.issues[i].update(data)
                return self.issues[i]
        raise AssertionError((method, path))


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.board = Board()
        inventory = patch.object(
            desk,
            "live_sessions",
            return_value=[{"name": n, "running": True} for n in ("studio", "one", "two")],
        )
        self.inventory = inventory.start()
        self.addCleanup(inventory.stop)
        self.plan = {
            "companyId": "c1",
            "requestId": str(uuid.uuid4()),
            "title": "ساخت صفحه",
            "steps": [
                {"title": "پیاده‌سازی", "assigneeAgentId": "agy"},
                {"title": "بازبینی", "description": "روی ویندوز", "assigneeAgentId": "Freebuff"},
            ],
        }

    def test_plan_assignments_and_replay_after_partial_failure(self):
        self.board.fail_title = "بازبینی"
        with self.assertRaisesRegex(PaperclipError, "1 of 2"):
            desk.save_plan(self.board, "c1", self.plan)
        self.assertEqual(len(self.board.issues), 2)
        self.board.fail_title = None
        r = desk.save_plan(self.board, "c1", self.plan)
        self.assertEqual(len(self.board.issues), 3)
        self.assertEqual([i["parentId"] for i in r["children"]], [r["parent"]["id"]] * 2)
        self.assertEqual([i["assigneeAgentId"] for i in r["children"]], ["agy", "Freebuff"])
        self.assertTrue(all(v["status"] == "backlog" for v in self.board.issues.values()))
        self.assertTrue(all((m, p) == ("POST", "/api/companies/c1/issues") for m, p, _ in self.board.writes))

    def test_split_existing_parent_and_inherit_visibility_and_project(self):
        self.board.issues["current"] = {
            "id": "current",
            "companyId": "c1",
            "visibility": "private",
            "projectId": "proj",
        }
        desk.save_plan(self.board, "c1", dict(self.plan, parentId="current", title=""))
        self.assertEqual(len(self.board.writes), 2)
        for _, _, data in self.board.writes:
            self.assertEqual(
                (data["parentId"], data["visibility"], data["projectId"]), ("current", "private", "proj")
            )

    def test_invalid_members_or_parent_do_not_partially_write(self):
        for status in ("pending_approval", "paused", "terminated", "unknown"):
            self.board.members[0]["status"] = status
            with self.assertRaises(PaperclipError):
                desk.save_plan(self.board, "c1", self.plan)
        self.board.members[0]["status"] = "active"
        self.board.issues["other"] = {"id": "other", "companyId": "someone-else"}
        with self.assertRaises(PaperclipError):
            desk.save_plan(self.board, "c1", dict(self.plan, parentId="other"))
        for invalid in (
            dict(self.plan, steps=[]),
            dict(self.plan, requestId="bad"),
            dict(self.plan, steps=[{}]),
            dict(self.plan, steps=[self.plan["steps"][0]] * 21),
        ):
            with self.assertRaises(PaperclipError):
                desk.save_plan(self.board, "c1", invalid)
        self.assertFalse(self.board.writes)

    def test_enrollment_uses_fixed_process_and_respects_approval(self):
        data = dict(
            name="My AGY",
            mode="agent",
            target="agy-worker",
            kind="agy",
            terminal="",
            session="studio",
            companyId="c1",
        )
        with (
            patch.object(desk, "herdr_binary", return_value="test-cli"),
            patch.object(
                desk, "live_targets", return_value=[{"kind": "agy", "target": "agy-worker", "terminal": ""}]
            ) as discovery,
        ):
            r = desk.enroll(self.board, "c1", data)
            discovery.assert_called_once_with("studio")
            self.assertTrue(r["needsApproval"])
            self.assertEqual(r["agent"]["status"], "pending_approval")
            self.assertNotIn("adapterConfig", r["agent"])
            self.assertTrue(desk.enroll(self.board, "c1", data)["existing"])
            for bad in (
                dict(data, command="no"),
                dict(data, HERDR_DESK_EXE="no"),
                dict(data, session="../no"),
                dict(data, session=None),
                dict(data, session="other"),
                dict(data, name="another"),
                dict(data, name="new", target="missing"),
                dict(data, name="new", session="Studio"),
                dict(data, mode="manual", target=""),
                dict(data, name="new", terminal="old-terminal"),
            ):
                with self.assertRaises(PaperclipError):
                    desk.enroll(self.board, "c1", bad)
        self.assertEqual(len(self.board.writes), 1)
        _, route, hire = self.board.writes[0]
        self.assertEqual(route, "/api/companies/c1/agent-hires")
        self.assertEqual(hire["adapterConfig"]["command"], sys.executable)
        self.assertEqual(
            hire["adapterConfig"]["args"],
            ["-E", "-s", str(desk.WORKER), "agent", "agy-worker", "", "agy", "studio"],
        )
        self.assertEqual(hire["runtimeConfig"]["heartbeat"]["maxConcurrentRuns"], 1)
        self.assertEqual(hire["adapterConfig"]["env"], {"HERDR_DESK_EXE": "test-cli"})
        self.assertEqual(hire["metadata"]["herdrDesk"]["session"], "studio")

    def test_same_target_different_sessions_and_legacy_unscoped_collision(self):
        data = dict(name="New worker", mode="agent", target="w1:p1", terminal="t", kind="agy", session="two")
        old = dict(mode="agent", target="w1:p1", terminal="t", kind="agy")
        self.board.members[0]["metadata"] = {"herdrDesk": old}
        with (
            patch.object(desk, "herdr_binary", return_value="test-cli"),
            patch.object(desk, "live_targets", return_value=[old]) as scan,
        ):
            with self.assertRaisesRegex(PaperclipError, "already linked"):
                desk.enroll(self.board, "c1", data)
            scan.assert_not_called()
            old["session"] = "one"
            desk.enroll(self.board, "c1", data)
            scan.assert_called_once_with("two")
        self.assertEqual(self.board.writes[0][2]["metadata"]["herdrDesk"]["session"], "two")

    def test_idle_but_not_verified_cannot_be_assigned_or_released(self):
        member = self.board.members[0]
        member.update(adapterType="hermes_local", lifecycleState="verifying", lifecycleError="private")
        self.board.issues["i"] = dict(id="i", companyId="c1", assigneeAgentId=member["id"], status="backlog")
        summary = desk.agent_summary(member)
        self.assertTrue(summary["verificationFailed"])
        self.assertFalse(summary["assignable"])
        self.assertNotIn("private", str(summary))
        with self.assertRaises(PaperclipError):
            desk.save_plan(self.board, "c1", self.plan)
        with self.assertRaises(PaperclipError):
            desk.advance(self.board, "c1", dict(action="release", issueId="i", assigneeAgentId=member["id"]))
        self.assertFalse(self.board.writes)
        self.assertTrue(desk.eligible(dict(member, lifecycleState="ready")))

    def test_pane_replacement_and_closed_parent_are_rejected_before_writes(self):
        with (
            patch.object(desk, "herdr_binary", return_value="test-cli"),
            patch.object(
                desk, "live_targets", return_value=[{"target": "w1:p1", "terminal": "new", "kind": "agy"}]
            ),
        ):
            with self.assertRaises(PaperclipError):
                desk.enroll(
                    self.board,
                    "c1",
                    dict(
                        name="Engine",
                        mode="agent",
                        target="w1:p1",
                        terminal="old",
                        kind="agy",
                        session="studio",
                    ),
                )
        self.board.issues["closed"] = {"id": "closed", "status": "done", "companyId": "c1"}
        with self.assertRaises(PaperclipError):
            desk.save_plan(self.board, "c1", dict(self.plan, parentId="closed"))
        self.assertFalse(self.board.writes)

    def test_manual_release_and_review_are_explicit_and_scoped(self):
        with patch.object(desk, "live_targets", side_effect=AssertionError("manual must not call Herdr")):
            r = desk.enroll(self.board, "c1", {"name": "manual tester", "mode": "manual", "companyId": "c1"})
        _, _, hire = self.board.writes[-1]
        self.inventory.assert_not_called()
        self.assertFalse(hire["runtimeConfig"]["heartbeat"]["wakeOnDemand"])
        self.assertEqual(hire["adapterConfig"]["args"][-1], "manual")
        agent = r["agent"]["id"]
        self.board.members[-1]["status"] = "idle"
        self.board.issues["i"] = dict(
            id="i", companyId="c1", status="backlog", assigneeAgentId=agent, statusVersion=1
        )
        data = {"companyId": "c1", "issueId": "i", "assigneeAgentId": agent, "action": "release"}
        with self.assertRaises(PaperclipError):
            desk.advance(self.board, "c1", dict(data, assigneeAgentId="changed"))
        self.assertEqual(desk.advance(self.board, "c1", data)["issue"]["status"], "in_progress")
        self.assertEqual(
            desk.advance(self.board, "c1", dict(data, action="review"))["issue"]["status"], "in_review"
        )
        self.assertEqual(self.board.writes[-2][2]["resolverPolicy"], "human_only")
        self.assertEqual(self.board.writes[-1][2]["reviewInteractionId"], "decision")
        self.assertFalse(any("heartbeat/invoke" in p for _, p, _ in self.board.writes))

    def test_http_boundaries_and_sanitized_roster(self):
        self.board.members[0]["adapterConfig"] = {"env": {"SECRET": "never send me"}}
        with (
            serving(app.DashboardHandler) as server,
            patch.object(app, "COMPANY_ID", ""),
            patch.object(app, "paperclip_json", self.board),
        ):
            url = f"http://127.0.0.1:{server.server_port}"
            with urlopen(url + "/api/agents", timeout=5) as response:
                self.assertNotIn("never send me", response.read().decode())
            with self.assertRaises(HTTPError) as cm:
                urlopen(Request(url + "/api/tickets", headers={"Host": "not-local.example"}), timeout=5)
            self.assertEqual(cm.exception.code, 403)
            cm.exception.close()
            for route, headers, data, expected in [
                ("/api/plans", {"Origin": "https://elsewhere.invalid"}, self.plan, 403),
                ("/api/team/enroll", {"Host": "not-local.example"}, {}, 403),
                ("/api/work/advance", {"Sec-Fetch-Site": "cross-site"}, {}, 403),
                ("/api/plans", {"Content-Type": "text/plain"}, self.plan, 415),
                ("/api/plans", {}, dict(self.plan, companyId="other"), 409),
                ("/api/plans", {}, ["bad body"], 400),
            ]:
                req = Request(
                    url + route,
                    method="POST",
                    data=json.dumps(data).encode(),
                    headers={"Content-Type": "application/json", **headers},
                )
                with self.assertRaises(HTTPError) as cm:
                    urlopen(req, timeout=5)
                self.assertEqual(cm.exception.code, expected)
                cm.exception.close()
            self.assertFalse(self.board.writes)
            with urlopen(
                Request(
                    url + "/api/plans",
                    data=json.dumps(self.plan).encode(),
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            ) as reply:
                self.assertEqual(len(json.load(reply)["children"]), 2)
