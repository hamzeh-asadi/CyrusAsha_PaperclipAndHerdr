"""Company-scoped operations for the local team desk. Paperclip is the sole store."""

import re
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

from desk_text import Message, error_detail
from herdr_worker import bound_agent, herdr_binary, live_sessions, live_targets, prompt_ready, safe_session
from paperclip_client import PaperclipError, request_human_review

ASSIGNABLE = ("active", "idle", "running")
AGENT_FIELDS = ("id", "name", "role", "adapterType", "status", "lastHeartbeatAt")
ISSUE_FIELDS = ("id", "identifier", "title", "description", "status", "parentId", "assigneeAgentId")
WORKER = Path(__file__).resolve().with_name("herdr_worker.py")


def reject(message, status=400):
    raise PaperclipError(message, status)


def fields(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        reject(Message("err.fields"))


def text(value, label, limit=240, optional=False):
    if (
        not isinstance(value, str)
        or (not optional and not value.strip())
        or len(value) > limit
        or "\x00" in value
    ):
        reject(Message("err.fieldText", field=label, limit=limit))
    try:
        value.encode("utf-8")
    except UnicodeError:
        reject(Message("err.unicode"))
    return value.strip()


def company_path(company):
    return "/api/companies/" + quote(company, safe="")


def roster(api, company):
    rows = api(company_path(company) + "/agents")
    if not isinstance(rows, list) or not all(
        isinstance(r, dict) and r.get("id") and r.get("companyId", company) == company for r in rows
    ):
        reject(Message("err.roster"), 502)
    return rows


def connection(record):
    meta = record.get("metadata")
    link = meta.get("herdrDesk") if isinstance(meta, dict) else None
    if isinstance(link, dict) and link.get("mode") in ("manual", "agent"):
        result = {"mode": link["mode"], "target": link.get("target", "")}
        if link["mode"] == "agent" and "session" in link:
            result["session"] = link["session"]
        return result
    return None


def eligible(record):
    return (
        record.get("status") in ASSIGNABLE
        and record.get("lifecycleState", "ready") == "ready"
        and (record.get("orgChainHealth") or {}).get("status") != "invalid_org_chain"
    )


def agent_summary(record):
    summary = {k: record[k] for k in AGENT_FIELDS if k in record}
    if "lifecycleState" in record:
        summary["lifecycleState"] = record["lifecycleState"]
        if record["lifecycleState"] == "verifying" and record.get("lifecycleError"):
            summary["verificationFailed"] = True  # never expose raw errors or configuration
    if not eligible(record):
        summary["assignable"] = False
    if link := connection(record):
        summary["connection"] = link
    return summary


def title_marker(value):
    """Evidence from decoded API text, not a guess at the missing characters."""
    if isinstance(value, str):
        if "\ufffd" in value:
            return "replacement_character"
        if re.search(r"(?<!\S)\?{3,}(?!\S)", value):
            return "literal_question_marks"
    return None


def plan_title(value, label, *, creating=True):
    title = text(value, label, optional=not creating)
    # A selected parent is referenced by ID, never renamed as part of a plan.
    if creating and title_marker(title):
        reject(Message("err.unreadableTitle", field=label))
    return title


def issue_summary(record):
    summary = {k: record[k] for k in ISSUE_FIELDS if k in record}
    if marker := title_marker(record.get("title")):
        summary["titleWarning"] = marker
    return summary


def enroll(api, company, payload):
    fields(payload, ("companyId", "name", "mode", "target", "terminal", "kind", "session"))
    name = text(payload.get("name"), Message("field.name"), 80)
    mode = payload.get("mode")
    target = text(payload.get("target", ""), Message("field.target"), 120, True)
    if mode not in ("agent", "manual") or (mode == "agent") != bool(target):
        reject(Message("err.handoff"))
    link = {"mode": mode, "target": target}
    session = payload.get("session")
    if mode == "agent":
        if not safe_session(session):
            reject(Message("err.sessionName"))
        link["session"] = session
    elif session is not None:
        reject(Message("err.fields"))
    expected_kind = text(payload.get("kind", ""), Message("field.kind"), 100, True)
    expected_terminal = text(payload.get("terminal", ""), Message("field.terminal"), 200, True)
    if (mode == "agent" and not expected_kind) or (mode == "manual" and (expected_kind or expected_terminal)):
        reject(Message("err.reselect"))
    rows = roster(api, company)
    for row in rows:
        if row.get("status") == "terminated":
            continue
        if row.get("name", "").strip().casefold() == name.casefold():
            if connection(row) == link:
                saved = row["metadata"]["herdrDesk"]
                if mode == "agent" and (saved.get("terminal"), saved.get("kind")) != (
                    expected_terminal,
                    expected_kind,
                ):
                    reject(
                        Message("err.oldBinding"),
                        409,
                    )
                return {"agent": agent_summary(row), "existing": True}
            reject(Message("err.duplicateName"), 409)
        other = connection(row) or {}
        if (
            mode == "agent"
            and other.get("mode") == "agent"
            and other.get("target") == target
            and (not other.get("session") or other["session"] == session)
        ):
            reject(Message("err.duplicateTarget"), 409)
    args = ["-E", "-s", str(WORKER), mode]
    if mode == "agent":
        try:
            binary = herdr_binary()
            # Match the spelling Herdr enumerated, including on case-insensitive Windows.
            running = {s["name"] for s in live_sessions() if s["running"]}
            candidates = live_targets(session) if session in running else []
            matches = [row for row in candidates if row["target"] == target]
        except RuntimeError as exc:
            reject(error_detail(exc), 503)
        if len(matches) != 1 or (matches[0]["terminal"], matches[0]["kind"]) != (
            expected_terminal,
            expected_kind,
        ):
            reject(Message("err.staleTarget"), 409)
        binding = matches[0]
        link.update(terminal=binding["terminal"], kind=binding["kind"])
        args.extend([target, binding["terminal"], binding["kind"], session])
    # Paths, command, environment and adapter type are NOT browser inputs.
    config = {
        "name": name,
        "role": "engineer",
        "adapterType": "process",
        "adapterConfig": {
            "command": sys.executable,
            "args": args,
            "cwd": str(WORKER.parent),
            "timeoutSec": 1900,
        },
        "runtimeConfig": {
            "heartbeat": {"enabled": False, "wakeOnDemand": mode == "agent", "maxConcurrentRuns": 1}
        },
        "metadata": {"herdrDesk": link},
    }
    if mode == "agent":
        config["adapterConfig"]["env"] = {"HERDR_DESK_EXE": binary}
    # Preserve the company's hiring/approval policy. Never auto-approve a hire.
    result = api(company_path(company) + "/agent-hires", "POST", data=config)
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("agent"), dict)
        or not result["agent"].get("id")
    ):
        reject(Message("err.hire"), 502)
    return {
        "agent": agent_summary(result["agent"]),
        "existing": False,
        "needsApproval": bool(result.get("approval")),
    }


def get_issue(api, company, issue_id):
    path = "/api/issues/" + quote(text(issue_id, Message("field.issue"), 100), safe="")
    issue = api(path)
    if not isinstance(issue, dict) or issue.get("companyId") != company or issue.get("id") != issue_id:
        reject(Message("err.otherCompany"), 404)
    return issue


def save_plan(api, company, payload):
    fields(payload, ("companyId", "requestId", "parentId", "title", "steps"))
    try:
        key = "herdr-desk:" + str(uuid.UUID(str(payload.get("requestId"))))
    except ValueError:
        reject(Message("err.planId"))
    parent_id = text(payload.get("parentId", ""), Message("field.parent"), 100, True)
    title = plan_title(payload.get("title", ""), Message("field.parentTitle"), creating=not parent_id)
    steps = payload.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        reject(Message("err.stepCount"))
    members = {a["id"] for a in roster(api, company) if eligible(a)}
    children = []
    for n, step in enumerate(steps, 1):
        fields(step, ("title", "description", "assigneeAgentId"))
        assignee = text(step.get("assigneeAgentId"), Message("work.owner"), 100)
        if assignee not in members:
            reject(Message("err.assignee"), 409)
        children.append(
            {
                "title": plan_title(step.get("title"), Message("step.number", n=n)),
                "assigneeAgentId": assignee,
                "description": text(step.get("description", ""), Message("step.description"), 3000, True),
            }
        )
    # Validate every row BEFORE the first write. Backlog deliberately does not wake agents.
    route = company_path(company) + "/issues"

    def create(suffix, data):
        row = api(
            route,
            "POST",
            data={**data, "status": "backlog", "idempotencyKey": key + ":" + suffix, "allowDuplicate": True},
        )
        if not isinstance(row, dict) or not row.get("id") or row.get("companyId") != company:
            reject(Message("err.createIssue"), 502)
        if any(row.get(k) != data.get(k) for k in ("title", "parentId", "assigneeAgentId")) or (
            "description" in data and (row.get("description") or "") != data["description"]
        ):
            reject(Message("err.replay"), 409)
        return row

    parent = get_issue(api, company, parent_id) if parent_id else create("parent", {"title": title})
    if parent.get("status") in ("done", "cancelled"):
        reject(Message("err.closed"), 409)
    created = []
    for index, child in enumerate(children):
        data = {
            **child,
            "parentId": parent["id"],
            "projectId": parent.get("projectId"),
            "visibility": parent.get("visibility") or "open",
        }
        try:
            created.append(issue_summary(create(str(index), data)))
        except PaperclipError as exc:
            raise PaperclipError(
                Message(
                    "err.partial",
                    id=parent.get("identifier") or parent["id"],
                    count=len(created),
                    total=len(children),
                    reason=error_detail(exc),
                ),
                exc.status,
            ) from exc
    return {"parent": issue_summary(parent), "children": created}


def require_ready_target(member):
    """A release must not queue work to an agent that is still onboarding."""
    link = (member.get("metadata") or {}).get("herdrDesk") or {}
    target = link.get("target", "")
    try:
        info = bound_agent(target, link.get("terminal", ""), link.get("kind", ""), link.get("session"))
    except (RuntimeError, ValueError):
        reject(Message("err.targetUnavailable", target=target), 409)
    if not prompt_ready(info):
        # Onboarding, a sign-in screen or a busy turn would block the ticket later.
        reject(Message("err.targetNotReady", target=target, state=str(info.get("agent_status") or "unknown")), 409)


def advance(api, company, payload):
    fields(payload, ("companyId", "issueId", "assigneeAgentId", "action"))
    issue = get_issue(api, company, payload.get("issueId"))
    member = next(
        (
            a
            for a in roster(api, company)
            if a["id"] == issue.get("assigneeAgentId")
            and a["id"] == payload.get("assigneeAgentId")
            and eligible(a)
        ),
        None,
    )
    if not member:
        reject(Message("err.ownerChanged"), 409)
    manual = (connection(member) or {}).get("mode") == "manual"
    if payload.get("action") == "release" and issue["status"] == "backlog":
        status = "in_progress" if manual else "todo"
    elif payload.get("action") == "review" and manual and issue["status"] == "in_progress":
        status = "in_review"
    else:
        reject(Message("err.transition"), 409)
    if status == "todo":
        require_ready_target(member)
    path = "/api/issues/" + quote(issue["id"], safe="")
    if status == "in_review":
        result = request_human_review(api, path, f"{issue['id']}:{issue['statusVersion']}")
    else:
        patch = {"status": status}
        if status == "todo":
            patch["expectedStatusVersion"] = issue["statusVersion"]
        result = api(path, "PATCH", data=patch)
    if not isinstance(result, dict) or result.get("id") != issue["id"] or result.get("status") != status:
        reject(Message("err.update"), 409)
    return {"issue": issue_summary(result)}
