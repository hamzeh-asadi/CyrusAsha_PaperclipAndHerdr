"""Portable Paperclip `process` worker. Uses the per-run identity, NEVER dashboard/.env.

Only Herdr's agent API can receive text. An unrecognised TUI (or a bare shell)
uses the manual handoff in the desk instead; no raw keystrokes go to panes.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import quote, urlencode

from paperclip_client import PaperclipError, request_json, request_human_review


def cli_text(*args, timeout=8):
    binary = shutil.which("herdr.exe" if os.name == "nt" else "herdr")
    if not binary:
        raise RuntimeError("Herdr در PATH نیست. برای تحویل دستی به آن نیاز ندارید.")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PAPERCLIP_")}
    try:
        result = subprocess.run(
            [binary, *args],
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
        )
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Herdr پاسخ معتبر نداد. برنامه و نشست ایجنت را با همان کاربر باز کنید.") from None


def herdr(*args, timeout=8):
    try:
        payload = json.loads(cli_text(*args, timeout=timeout))["result"]
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (TypeError, ValueError, KeyError):
        raise RuntimeError("پاسخ JSON معتبر از Herdr دریافت نشد.") from None


def safe_target(value):
    return isinstance(value, str) and re.fullmatch(r"[\w][\w.:-]{0,119}", value) is not None


def live_targets():
    records = herdr("agent", "list").get("agents")
    if not isinstance(records, list):
        raise RuntimeError("قالب فهرست ایجنت‌های Herdr شناخته نشد.")
    targets = []
    for item in records:
        if not isinstance(item, dict):
            continue
        # A display label/kind is not a unique CLI target. Unnamed agents must
        # stay pinned to their terminal identity; pane numbers can be recycled.
        target = item.get("name") or item.get("pane_id")
        terminal = "" if item.get("name") else item.get("terminal_id")
        kind = item.get("agent")
        if (
            safe_target(target)
            and isinstance(terminal, str)
            and (item.get("name") or terminal)
            and isinstance(kind, str)
            and kind
        ):
            targets.append(
                {
                    "target": target,
                    "terminal": terminal,
                    "kind": kind,
                    "name": item.get("name"),
                    "pane_id": item.get("pane_id"),
                    "status": item.get("agent_status", "unknown"),
                }
            )
    return targets


def bound_agent(target, terminal, kind):
    if not safe_target(target):
        raise ValueError("Invalid Herdr target")
    info = herdr("agent", "get", target).get("agent")
    if (
        not isinstance(info, dict)
        or not info.get("terminal_id")
        or not kind
        or info.get("agent") != kind
        or (
            info.get("name") != target
            if not terminal
            else (info.get("pane_id") != target or info.get("terminal_id") != terminal)
        )
    ):
        raise RuntimeError("نشست Herdr دیگر با اتصال ثبت‌شده مطابقت ندارد.")
    return info


def select_work(board, company, agent, run_id):
    # The process adapter does not always export TASK_ID. For an issue-scoped
    # wake, read the *actual* run, not the first item on the company's board.
    run = board("/api/heartbeat-runs/" + quote(run_id, safe=""))
    if (run.get("id"), run.get("companyId"), run.get("agentId")) != (run_id, company, agent):
        raise RuntimeError("Run identity mismatch; no prompt sent.")
    if any(
        run.get(k)
        for k in ("retryOfRunId", "processLossRetryCount", "scheduledRetryAttempt", "continuationAttempt")
    ):
        raise RuntimeError(
            "Automatic retry after an earlier attempt. Inspect the terminal before re-dispatching."
        )
    context = run.get("contextSnapshot") or {}
    task_id = (
        run.get("issueId") or context.get("issueId") or context.get("taskId") or os.getenv("PAPERCLIP_TASK_ID")
    )
    if task_id:
        if os.getenv("PAPERCLIP_TASK_ID", task_id) != task_id:
            raise RuntimeError("Inconsistent wake context; no prompt sent.")
        rows = [board("/api/issues/" + quote(task_id, safe=""))]
    elif run.get("invocationSource") == "on_demand" and run.get("triggerDetail") == "manual":
        query = urlencode({"assigneeAgentId": agent, "status": "todo"})
        rows = board(f"/api/companies/{quote(company, safe='')}/issues?{query}")
    else:
        return None
    for issue in rows:
        if (
            issue.get("companyId") == company
            and issue.get("assigneeAgentId") == agent
            and (not task_id or issue.get("id") == task_id)
            and (
                issue.get("status") == "todo"
                or (issue.get("status") == "in_progress" and issue.get("checkoutRunId") == run_id)
            )
        ):
            return issue
    return None


def run(target, terminal, kind):
    if not safe_target(target):
        raise ValueError("Invalid Herdr target")
    company, agent, run_id, url, key = (
        os.environ["PAPERCLIP_" + name] for name in ("COMPANY_ID", "AGENT_ID", "RUN_ID", "API_URL", "API_KEY")
    )

    def board(path, method="GET", data=None):
        return request_json(url, path, method, key=key, run_id=run_id, data=data, timeout=15)

    issue = select_work(board, company, agent, run_id)
    if not issue:
        print("No assigned ready task.")
        return
    path = "/api/issues/" + quote(issue["id"], safe="")
    info = bound_agent(target, terminal, kind)
    if info.get("agent_status") not in ("idle", "done") or info.get("interactive_ready") is not True:
        raise RuntimeError("Herdr target is not idle and ready. No prompt sent.")
    if issue["status"] == "todo":
        try:
            checked = board(path + "/checkout", "POST", {"agentId": agent, "expectedStatuses": ["todo"]})
        except PaperclipError as exc:
            if exc.status == 409:
                print("Task already claimed; no prompt sent.")
                return
            raise
        if not isinstance(checked, dict) or any(
            checked.get(k) != v
            for k, v in {
                "id": issue["id"],
                "companyId": company,
                "assigneeAgentId": agent,
                "checkoutRunId": run_id,
                "status": "in_progress",
            }.items()
        ):
            raise RuntimeError("Unconfirmed checkout. No prompt sent.")
        issue = checked
    text = f"Paperclip {issue.get('identifier') or issue['id']}: {issue['title']}. {issue.get('description') or ''}"
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text)[:12000]
    # A blocked, timed out or vanished agent never marks an issue successful.
    try:
        end = herdr("agent", "prompt", target, text, "--wait", "--timeout", "1800000", timeout=1810).get(
            "agent"
        )
    except RuntimeError as exc:
        raise RuntimeError("Delivery outcome unknown. Inspect the terminal before retrying.") from exc
    if (
        not isinstance(end, dict)
        or end.get("agent_status") not in ("idle", "done")
        or not info.get("terminal_id")
        or end.get("terminal_id") != info["terminal_id"]
        or end.get("agent") != kind
    ):
        raise RuntimeError("Agent did not finish on the same terminal. Inspect Herdr; task left open.")
    try:
        request_human_review(board, path, run_id)
    except PaperclipError as exc:
        raise RuntimeError(
            f"Herdr finished. Repair the human review in Paperclip; do NOT repeat the prompt. {exc}"
        ) from exc
    print("Handoff complete; awaiting human review.")


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["manual"]:
            print("Manual agent: copy the assigned task from the desk into your running CLI. No prompt sent.")
        elif len(sys.argv) == 5 and sys.argv[1] == "agent":
            run(*sys.argv[2:])
        else:
            raise ValueError("Invalid worker configuration")
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        sys.exit(f"Paperclip/Herdr: {error}")
