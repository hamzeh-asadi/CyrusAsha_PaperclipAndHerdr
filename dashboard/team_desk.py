"""Company-scoped operations for the local team desk. Paperclip is the sole store."""

from pathlib import Path
import sys
import uuid
from urllib.parse import quote

from desk_text import Message, error_detail
from herdr_worker import live_targets
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
        return {"mode": link["mode"], "target": link.get("target", "")}
    return None


def eligible(record):
    return (
        record.get("status") in ASSIGNABLE
        and (record.get("orgChainHealth") or {}).get("status") != "invalid_org_chain"
    )


def agent_summary(record):
    summary = {k: record[k] for k in AGENT_FIELDS if k in record}
    if (record.get("orgChainHealth") or {}).get("status") == "invalid_org_chain":
        summary["assignable"] = False
    if link := connection(record):
        summary["connection"] = link
    return summary


def issue_summary(record):
    return {k: record[k] for k in ISSUE_FIELDS if k in record}


def enroll(api, company, payload):
    fields(payload, ("companyId", "name", "mode", "target", "terminal", "kind"))
    name = text(payload.get("name"), Message("field.name"), 80)
    mode = payload.get("mode")
    target = text(payload.get("target", ""), Message("field.target"), 120, True)
    if mode not in ("agent", "manual") or (mode == "agent") != bool(target):
        reject(Message("err.handoff"))
    link = {"mode": mode, "target": target}
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
        if mode == "agent" and connection(row) == link:
            reject(Message("err.duplicateTarget"), 409)
    args = ["-E", "-s", str(WORKER), mode]
    if mode == "agent":
        try:
            matches = [row for row in live_targets() if row["target"] == target]
        except RuntimeError as exc:
            reject(error_detail(exc), 503)
        if len(matches) != 1 or (matches[0]["terminal"], matches[0]["kind"]) != (
            expected_terminal,
            expected_kind,
        ):
            reject(Message("err.staleTarget"), 409)
        binding = matches[0]
        link.update(terminal=binding["terminal"], kind=binding["kind"])
        args.extend([target, binding["terminal"], binding["kind"]])
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
    title = text(payload.get("title", ""), Message("field.parentTitle"), optional=bool(parent_id))
    steps = payload.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        reject(Message("err.stepCount"))
    members = {a["id"] for a in roster(api, company) if eligible(a)}
    children = []
    for step in steps:
        fields(step, ("title", "description", "assigneeAgentId"))
        assignee = text(step.get("assigneeAgentId"), Message("work.owner"), 100)
        if assignee not in members:
            reject(Message("err.assignee"), 409)
        children.append(
            {
                "title": text(step.get("title"), Message("step.title")),
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
